import config
import requests
import time
from collections import defaultdict
from decimal import Decimal, ROUND_DOWN
import os
from pybit.unified_trading import HTTP
import telebot


# ========== CONFIGURACIÓN ==========
SYMBOL = input("➡️  ticker: ").strip().upper() + "USDT"
API_BASE = "http://localhost:8000"
AGRUPACION = float(input("➡️  agrupación: "))  # Agrupación para el ticker
CHECK_INTERVAL = 1.5 # segundos

# Trading
MONTO_OPERACION = 25  # USDT por operación
DISTANCIA_SL_INICIAL = Decimal("2")  # x% de distancia para SL
AVANCE_PARA_MOVER_SL = Decimal("2")  # Mover el stop la primera vez para proteger 1 a 1 por ejemplo
MARGEN_PROTECCION = Decimal("2")  # x% de margen al mover SL (trailing stop)


# Telegram 
bot_token = config.token_telegram
bot = telebot.TeleBot(bot_token)
chat_id = config.chat_id

# Estado de posiciones
tracking_posiciones = {}
session = None

# ========== FUNCIÓN TELEGRAM =========
def enviar_telegram(mensaje):
    """Envía mensaje a Telegram"""
    try:
        bot.send_message(chat_id, mensaje, parse_mode='HTML')
    except Exception as e:
        print(f"❌ Error enviando a Telegram: {e}")

# ========== FUNCIONES BÁSICAS ==========
def inicializar_bybit():
    """Inicializa la sesión de Bybit"""
    global session
    session = HTTP(
        testnet=False,
        api_key=config.api_key,
        api_secret=config.api_secret,
    )

def get_tick_size(symbol):
    """Obtiene el tick size del símbolo"""
    try:
        info = session.get_instruments_info(category="linear", symbol=symbol)
        tick_size = Decimal(info["result"]["list"][0]["priceFilter"]["tickSize"])
        return tick_size
    except Exception as e:
        print(f"❌ Error obteniendo tick size: {e}")
        return Decimal("0.01")  # Valor por defecto

def adjust_price(symbol, price):
    """Ajusta el precio al tick size correcto"""
    try:
        tick_size = get_tick_size(symbol)
        price_decimal = Decimal(str(price))
        adjusted = (price_decimal / tick_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick_size
        return adjusted
    except:
        return Decimal(str(price))

def adjust_price_to_tick(price, tick_size):
    """Ajusta un precio según el tick size dado"""
    try:
        price_decimal = Decimal(str(price))
        tick_decimal = Decimal(str(tick_size))
        adjusted = (price_decimal / tick_decimal).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick_decimal
        return float(adjusted)
    except:
        return price

def qty_step(symbol, monto_usdt):
    """Calcula la cantidad ajustada al qty step"""
    try:
        # Obtener precio actual
        ticker = session.get_tickers(category="linear", symbol=symbol)
        price = Decimal(ticker["result"]["list"][0]["lastPrice"])
        
        # Obtener qty step
        info = session.get_instruments_info(category="linear", symbol=symbol)
        qty_step_value = Decimal(info["result"]["list"][0]["lotSizeFilter"]["qtyStep"])
        
        # Calcular cantidad
        qty = Decimal(str(monto_usdt)) / price
        qty_adjusted = (qty / qty_step_value).quantize(Decimal('1'), rounding=ROUND_DOWN) * qty_step_value
        
        return qty_adjusted
    except Exception as e:
        print(f"❌ Error calculando qty: {e}")
        return None

def get_current_position(symbol):
    """Obtiene la posición actual de un símbolo"""
    try:
        positions = session.get_positions(category="linear", symbol=symbol)
        return positions["result"]["list"]
    except:
        return []

def agrupar_precio(price):
    """Agrupa precio en niveles según AGRUPACION"""
    price_decimal = Decimal(str(price))
    agrup_decimal = Decimal(str(AGRUPACION))
    agrupado = (price_decimal / agrup_decimal).quantize(Decimal('1'), rounding=ROUND_DOWN) * agrup_decimal
    return float(agrupado)

def obtener_precio_actual():
    """Obtiene precio actual de Binance"""
    try:
        resp = requests.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={SYMBOL}", timeout=5)
        return float(resp.json()["price"])
    except:
        return None

def obtener_orderbook():
    """Obtiene order book desde API local"""
    try:
        resp = requests.get(f"{API_BASE}/orderbooks/{SYMBOL}", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None

def calcular_bloques(order_book, tick_size):
    """Calcula top 10 bloques con precio promedio ponderado ajustado al tick size"""
    bid_ranges = defaultdict(lambda: {'total_qty': 0, 'price_count': {}})
    ask_ranges = defaultdict(lambda: {'total_qty': 0, 'price_count': {}})
    
    # Agrupar BIDs
    for price, qty in order_book.get('bids', {}).items():
        price, qty = float(price), float(qty)
        range_key = agrupar_precio(price)
        bid_ranges[range_key]['total_qty'] += qty
        bid_ranges[range_key]['price_count'][price] = bid_ranges[range_key]['price_count'].get(price, 0) + qty
    
    # Agrupar ASKs
    for price, qty in order_book.get('asks', {}).items():
        price, qty = float(price), float(qty)
        range_key = agrupar_precio(price)
        ask_ranges[range_key]['total_qty'] += qty
        ask_ranges[range_key]['price_count'][price] = ask_ranges[range_key]['price_count'].get(price, 0) + qty
    
    # Top 10 bloques por volumen
    top_bids = sorted(bid_ranges.items(), key=lambda x: x[1]['total_qty'], reverse=True)[:10]
    top_asks = sorted(ask_ranges.items(), key=lambda x: x[1]['total_qty'], reverse=True)[:10]
    
    # Calcular precio promedio ponderado y ajustar al tick size
    bloques_long = []
    for pr_range, data in top_bids:
        total_qty = data['total_qty']
        if total_qty > 0:
            precio_ponderado = sum(p * q for p, q in data['price_count'].items()) / total_qty
            # ✅ AJUSTAR AL TICK SIZE
            precio_ajustado = adjust_price_to_tick(precio_ponderado, tick_size)
            bloques_long.append({'precio': precio_ajustado, 'volumen': total_qty})
    
    bloques_short = []
    for pr_range, data in top_asks:
        total_qty = data['total_qty']
        if total_qty > 0:
            precio_ponderado = sum(p * q for p, q in data['price_count'].items()) / total_qty
            # ✅ AJUSTAR AL TICK SIZE
            precio_ajustado = adjust_price_to_tick(precio_ponderado, tick_size)
            bloques_short.append({'precio': precio_ajustado, 'volumen': total_qty})
    
    # Ordenar por precio (LONG: mayor a menor, SHORT: menor a mayor)
    bloques_long.sort(key=lambda x: x['precio'], reverse=True)
    bloques_short.sort(key=lambda x: x['precio'])
    
    return bloques_long, bloques_short

# ========== MACHINE LEARNING ==========
def cargar_modelo_ml():
    """Carga el modelo ML entrenado"""
    try:
        import joblib
        if os.path.exists('modelo_orderbook_bloques.pkl'):
            modelo = joblib.load('modelo_orderbook_bloques.pkl')
            scaler = joblib.load('scaler_orderbook.pkl')
            features = joblib.load('feature_names_orderbook.pkl')
            print("✅ Modelo ML cargado\n")
            return modelo, scaler, features
    except Exception as e:
        print(f"⚠️  Error cargando modelo: {e}")
    
    print("❌ Sin modelo ML - bot no puede funcionar\n")
    return None, None, None

def predecir_mejor_bloque(bloques, precio_actual, es_long, modelo, scaler, features):
    """Usa ML para predecir el mejor bloque de entrada"""
    if modelo is None or len(bloques) < 2:
        return None
    
    try:
        import pandas as pd
        import numpy as np
        
        # Crear features para cada bloque
        datos = []
        for i, bloque in enumerate(bloques, 1):
            precio = bloque['precio']
            volumen = bloque['volumen']
            dist_pct = abs((precio - precio_actual) / precio_actual * 100)
            
            features_bloque = {
                'es_long': 1 if es_long else 0,
                'num_bloque': i,
                'volumen': volumen,
                'distancia_pct': dist_pct,
                'vol_short_entrada': 0,
                'dist_short_entrada': 0,
                'vol_short_stop': 0,
                'dist_short_stop': 0,
                'vol_long_entrada': 0,
                'dist_long_entrada': 0,
                'vol_long_stop': 0,
                'dist_long_stop': 0,
                'vol_mi_entrada': 0,
                'vol_mi_stop': 0,
                'dist_mi_stop': 0,
                'ratio_entrada_stop': 0,
                'ratio_long_short_entrada': 0,
                'ratio_short_long_entrada': 0
            }
            datos.append(features_bloque)
        
        # Crear DataFrame
        X = pd.DataFrame(datos)
        X['volumen_log'] = np.log1p(X['volumen'])
        X['distancia_log'] = np.log1p(X['distancia_pct'])
        X['ranking_norm'] = X['num_bloque'] / 10.0
        X['vol_mi_entrada_log'] = np.log1p(X['vol_mi_entrada'])
        X['vol_mi_stop_log'] = np.log1p(X['vol_mi_stop'])
        X['vol_short_entrada_log'] = np.log1p(X['vol_short_entrada'])
        X['vol_long_entrada_log'] = np.log1p(X['vol_long_entrada'])
        
        X = X[features]
        X_scaled = scaler.transform(X)
        
        # Predecir probabilidades
        probabilidades = modelo.predict_proba(X_scaled)
        
        # Buscar mejor bloque de entrada (clase 2 = entrada)
        mejor_idx = None
        mejor_prob = 0
        
        for i, probs in enumerate(probabilidades):
            if len(probs) > 2:
                prob_entrada = probs[2]  # Clase 2 = ENTRADA
                if prob_entrada > mejor_prob:
                    mejor_prob = prob_entrada
                    mejor_idx = i
        
        if mejor_idx is not None:
            return bloques[mejor_idx]
        
    except Exception as e:
        print(f"❌ Error en ML: {e}")
    
    return None

# ========== MONITOREO ==========
def monitorear_precio(entrada_long, entrada_short):
    """Monitorea distancias en tiempo real y detecta cualquier toque"""
    print(f"\n👁️  Monitoreando ambos lados")
    print("="*60)
    
    precio_anterior = obtener_precio_actual()
    
    while True:
        time.sleep(CHECK_INTERVAL)
        precio_actual = obtener_precio_actual()
        
        if precio_actual is None:
            continue
        
        # Calcular distancias
        dist_long = abs((entrada_long - precio_actual) / precio_actual * 100)
        dist_short = abs((entrada_short - precio_actual) / precio_actual * 100)
        
        # Mostrar estado actual
        print(f"\r💰 {SYMBOL} ${precio_actual:} | 🟢 LONG: {dist_long:.3f}% | 🔴 SHORT: {dist_short:.3f}%", end="", flush=True)
        
        # Detectar toque LONG
        if precio_anterior > entrada_long and precio_actual <= entrada_long:
            print(f"\n\n🎯 ¡TOQUE LONG! @ ${precio_actual:}")
            abrir_posicion_long(SYMBOL, MONTO_OPERACION, DISTANCIA_SL_INICIAL)
            print("🔄 Volviendo a analizar...\n")
            return True
        
        # Detectar toque SHORT
        if precio_anterior < entrada_short and precio_actual >= entrada_short:
            print(f"\n\n🎯 ¡TOQUE SHORT! @ ${precio_actual:}")
            abrir_posicion_short(SYMBOL, MONTO_OPERACION, DISTANCIA_SL_INICIAL)
            print("🔄 Volviendo a analizar...\n")
            return True
        
        precio_anterior = precio_actual

def abrir_posicion_long(symbol, monto_operacion, distancia_sl_porcentaje):
    """Abre una posición LONG en Bybit"""
    try:
        # Verificar si ya hay posición abierta
        positions_list = get_current_position(symbol)
        if positions_list and any(Decimal(position['size']) != 0 for position in positions_list):
            print(f"⚠️ Ya hay una posición abierta en {symbol}")
            return False

        # Calcular cantidad
        base_asset_qty_final = qty_step(symbol, monto_operacion)
        if base_asset_qty_final is None:
            return False

        # Abrir posición a mercado
        print(f"📤 Abriendo posición LONG: {base_asset_qty_final} {symbol}")
        response_market_order = session.place_order(
            category="linear",
            symbol=symbol,
            side="Buy",
            orderType="Market",
            qty=str(base_asset_qty_final),
        )

        time.sleep(1.5)
        if response_market_order['retCode'] != 0:
            print("❌ Error al abrir la posición LONG")
            return False

        # Obtener precio de entrada
        positions_list = get_current_position(symbol)
        current_price = Decimal(positions_list[0]['avgPrice'])

        # Calcular y colocar stop loss
        distancia_decimal = distancia_sl_porcentaje / Decimal(100)
        price_sl = adjust_price(symbol, current_price * (Decimal(1) - distancia_decimal))

        session.set_trading_stop(
            category="linear",
            symbol=symbol,
            stopLoss=str(price_sl),
            slTriggerBy="LastPrice",
            tpslMode="Full",
            slOrderType="Market",
        )

        # Inicializar tracking
        tracking_posiciones[symbol] = {
            "precio_maximo": current_price,
            "precio_entrada": current_price,
            "side": "Buy",
            "ultimo_nivel_protegido": Decimal(0)
        }

        mensaje_log = f"✅ LONG abierto: Entrada ${current_price}, SL ${price_sl} (-{float(distancia_sl_porcentaje):.2f}%)"
        print(mensaje_log)
        
        # ✅ ENVIAR A TELEGRAM
        mensaje_telegram = f"""
🟢 <b>POSICIÓN LONG ABIERTA</b>

Símbolo: <b>{symbol}</b>
Cantidad: <b>{base_asset_qty_final}</b>
Precio entrada: <b>${current_price}</b>
Stop Loss: <b>${price_sl}</b> (-{float(distancia_sl_porcentaje):.2f}%)
Monto: <b>${monto_operacion}</b>
"""
        enviar_telegram(mensaje_telegram)
        
        return True

    except Exception as e:
        print(f"❌ Error al abrir LONG: {e}")
        enviar_telegram(f"❌ Error al abrir LONG: {e}") 
        return False

def abrir_posicion_short(symbol, monto_operacion, distancia_sl_porcentaje):
    """Abre una posición SHORT en Bybit"""
    try:
        # Verificar si ya hay posición abierta
        positions_list = get_current_position(symbol)
        if positions_list and any(Decimal(position['size']) != 0 for position in positions_list):
            print(f"⚠️ Ya hay una posición abierta en {symbol}")
            return False

        # Calcular cantidad
        base_asset_qty_final = qty_step(symbol, monto_operacion)
        if base_asset_qty_final is None:
            return False

        # Abrir posición a mercado
        print(f"📤 Abriendo posición SHORT: {base_asset_qty_final} {symbol}")
        response_market_order = session.place_order(
            category="linear",
            symbol=symbol,
            side="Sell",
            orderType="Market",
            qty=str(base_asset_qty_final),
        )

        time.sleep(1.5)
        if response_market_order['retCode'] != 0:
            print("❌ Error al abrir la posición SHORT")
            return False

        # Obtener precio de entrada
        positions_list = get_current_position(symbol)
        current_price = Decimal(positions_list[0]['avgPrice'])

        # Calcular y colocar stop loss
        distancia_decimal = distancia_sl_porcentaje / Decimal(100)
        price_sl = adjust_price(symbol, current_price * (Decimal(1) + distancia_decimal))

        session.set_trading_stop(
            category="linear",
            symbol=symbol,
            stopLoss=str(price_sl),
            slTriggerBy="LastPrice",
            tpslMode="Full",
            slOrderType="Market",
        )

        # Inicializar tracking
        tracking_posiciones[symbol] = {
            "precio_minimo": current_price,
            "precio_entrada": current_price,
            "side": "Sell",
            "ultimo_nivel_protegido": Decimal(0)
        }

        mensaje_log = f"✅ SHORT abierto: Entrada ${current_price}, SL ${price_sl} (+{float(distancia_sl_porcentaje):.2f}%)"
        print(mensaje_log)
        
        # ✅ ENVIAR A TELEGRAM
        mensaje_telegram = f"""
🔴 <b>POSICIÓN SHORT ABIERTA</b>

Símbolo: <b>{symbol}</b>
Cantidad: <b>{base_asset_qty_final}</b>
Precio entrada: <b>${current_price}</b>
Stop Loss: <b>${price_sl}</b> (+{float(distancia_sl_porcentaje):.2f}%)
Monto: <b>${monto_operacion}</b>
"""
        enviar_telegram(mensaje_telegram)
        
        return True

    except Exception as e:
        print(f"❌ Error al abrir SHORT: {e}")
        enviar_telegram(f"❌ Error al abrir SHORT: {e}")
        return False

def monitorear_proteccion_progresiva():
    """Monitorea y mueve el SL"""
    while True:
        try:
            posiciones = session.get_positions(category="linear", settleCoin="USDT")
            for posicion in posiciones["result"]["list"]:
                size = Decimal(posicion["size"])
                if size == 0:
                    continue

                symbol = posicion["symbol"]
                side = posicion["side"]
                entry_price = Decimal(posicion["avgPrice"])

                if symbol not in tracking_posiciones:
                    time.sleep(10)
                    continue

                # Obtener precio actual
                tickers = session.get_tickers(symbol=symbol, category="linear")
                last_price = Decimal(tickers["result"]["list"][0]["lastPrice"])

                tracking_info = tracking_posiciones[symbol]
                precio_entrada = tracking_info["precio_entrada"]
                ultimo_nivel = tracking_info["ultimo_nivel_protegido"]

                if side == "Buy":
                    # LONG: Calcular ganancia actual
                    ganancia_pct = ((last_price - precio_entrada) / precio_entrada) * 100
                    
                    if ganancia_pct >= AVANCE_PARA_MOVER_SL * 2:
                        nivel_objetivo = (ganancia_pct // AVANCE_PARA_MOVER_SL) * AVANCE_PARA_MOVER_SL
                        nivel_proteccion = nivel_objetivo - MARGEN_PROTECCION
                        
                        if nivel_proteccion > ultimo_nivel:
                            nuevo_sl = precio_entrada * (Decimal(1) + nivel_proteccion / 100)
                            nuevo_sl = adjust_price(symbol, nuevo_sl)
                            
                            session.set_trading_stop(
                                category="linear",
                                symbol=symbol,
                                stopLoss=str(nuevo_sl),
                                slTriggerBy="LastPrice",
                                tpslMode="Full",
                                slOrderType="Market",
                            )
                            
                            tracking_posiciones[symbol]["ultimo_nivel_protegido"] = nivel_proteccion
                            mensaje = f"🛡️ LONG - SL movido a ${nuevo_sl} (protege +{float(nivel_proteccion):.2f}%)"
                            print(f"\n{mensaje}")
                            
                            # ✅ ENVIAR A TELEGRAM
                            mensaje_telegram = f"""
🛡️ <b>STOP LOSS ACTUALIZADO</b>

Símbolo: <b>{symbol}</b>
🟢 Tipo: <b>LONG</b>
Nuevo SL: <b>${nuevo_sl}</b>
Protege: <b>+{float(nivel_proteccion):.2f}%</b>
Precio actual: <b>${last_price}</b>
"""
                            enviar_telegram(mensaje_telegram)

                elif side == "Sell":
                    # SHORT: Calcular ganancia actual
                    ganancia_pct = ((precio_entrada - last_price) / precio_entrada) * 100
                    
                    if ganancia_pct >= AVANCE_PARA_MOVER_SL * 2:
                        nivel_objetivo = (ganancia_pct // AVANCE_PARA_MOVER_SL) * AVANCE_PARA_MOVER_SL
                        nivel_proteccion = nivel_objetivo - MARGEN_PROTECCION
                        
                        if nivel_proteccion > ultimo_nivel:
                            nuevo_sl = precio_entrada * (Decimal(1) - nivel_proteccion / 100)
                            nuevo_sl = adjust_price(symbol, nuevo_sl)
                            
                            session.set_trading_stop(
                                category="linear",
                                symbol=symbol,
                                stopLoss=str(nuevo_sl),
                                slTriggerBy="LastPrice",
                                tpslMode="Full",
                                slOrderType="Market",
                            )
                            
                            tracking_posiciones[symbol]["ultimo_nivel_protegido"] = nivel_proteccion
                            mensaje = f"🛡️ SHORT - SL movido a ${nuevo_sl} (protege +{float(nivel_proteccion):.2f}%)"
                            print(f"\n{mensaje}")
                            
                            # ✅ ENVIAR A TELEGRAM
                            mensaje_telegram = f"""
🛡️ <b>STOP LOSS ACTUALIZADO</b>

Símbolo: <b>{symbol}</b>
🔴 Tipo: <b>SHORT</b>
Nuevo SL: <b>${nuevo_sl}</b>
Protege: <b>+{float(nivel_proteccion):.2f}%</b>
Precio actual: <b>${last_price}</b>
"""
                            enviar_telegram(mensaje_telegram)

        except Exception as e:
            print(f"❌ Error en protección progresiva: {e}")

        time.sleep(10)

# ========== MAIN ==========
def main():
    print("\n" + "="*50)
    print("🤖 BOT ML + BYBIT TRADING")
    print("="*50 + "\n")
    
    # Inicializar Bybit
    inicializar_bybit()
    
    # ✅ OBTENER TICK SIZE DEL SÍMBOLO
    tick_size = get_tick_size(SYMBOL)
    print(f"📏 Tick size de {SYMBOL}: {tick_size}\n")
    
    # Cargar modelo ML
    modelo, scaler, features = cargar_modelo_ml()
    
    if modelo is None:
        print("❌ No se puede iniciar sin modelo ML")
        return
    
    # Iniciar monitoreo de protección progresiva en thread separado
    import threading
    thread_proteccion = threading.Thread(target=monitorear_proteccion_progresiva, daemon=True)
    thread_proteccion.start()
    print("✅ Sistema de protección progresiva activado\n")
    
    while True:
        try:
            # Obtener precio actual
            precio_actual = obtener_precio_actual()
            if not precio_actual:
                print("❌ Sin precio")
                time.sleep(5)
                continue
            
            print(f"💰 {SYMBOL}: ${precio_actual:,.4f}")
            
            # Obtener order book
            order_book = obtener_orderbook()
            if not order_book:
                print("❌ Sin order book")
                time.sleep(10)
                continue
            
            # ✅ CALCULAR BLOQUES CON TICK SIZE
            bloques_long, bloques_short = calcular_bloques(order_book, tick_size)
            
            if len(bloques_long) < 10 or len(bloques_short) < 10:
                print(f"⚠️  Bloques insuficientes (LONG: {len(bloques_long)}, SHORT: {len(bloques_short)})")
                time.sleep(10)
                continue
            
            print(f"📊 Bloques detectados: LONG={len(bloques_long)}, SHORT={len(bloques_short)}")
            
            # ML predice mejor bloque para LONG
            print("\n🤖 ML analizando bloques LONG...")
            mejor_long = predecir_mejor_bloque(bloques_long, precio_actual, True, modelo, scaler, features)
            
            if mejor_long:
                dist_long = abs((mejor_long['precio'] - precio_actual) / precio_actual * 100)
                print(f"🟢 LONG: ${mejor_long['precio']:.4f} | Vol: {mejor_long['volumen']:,.0f} | Dist: {dist_long:.3f}%")
            
            # ML predice mejor bloque para SHORT
            print("🤖 ML analizando bloques SHORT...")
            mejor_short = predecir_mejor_bloque(bloques_short, precio_actual, False, modelo, scaler, features)
            
            if mejor_short:
                dist_short = abs((mejor_short['precio'] - precio_actual) / precio_actual * 100)
                print(f"🔴 SHORT: ${mejor_short['precio']:.4f} | Vol: {mejor_short['volumen']:,.0f} | Dist: {dist_short:.3f}%")
            
            # Monitorear ambos lados
            if mejor_long and mejor_short:
                # Monitorear hasta que cualquiera toque
                monitorear_precio(mejor_long['precio'], mejor_short['precio'])
            else:
                print("❌ ML no pudo seleccionar bloques")
                time.sleep(10)
            
        except KeyboardInterrupt:
            print("\n\n👋 Bot detenido\n")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()