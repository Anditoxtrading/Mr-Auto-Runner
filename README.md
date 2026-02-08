# 🤖 Bot de Trading ML – Bybit Futures (Order Book Binance)

Bot de **trading automatizado** que utiliza **Machine Learning** para analizar el **order book de Binance** en tiempo real y ejecutar operaciones en **Bybit Futures**, incorporando **gestión de riesgo avanzada** y **alertas por Telegram**.

---

## 📋 Características

- 🧠 **Machine Learning**  
  Predice los mejores bloques de órdenes para entrar en posiciones LONG y SHORT.

- 📊 **Order Book en Tiempo Real**  
  Monitorea el order book de Binance Futures mediante WebSocket.

- ⚡ **Trading Automatizado**  
  Ejecuta operaciones automáticamente en Bybit Futures.

- 🛡️ **Gestión de Riesgo Avanzada**  
  Stop Loss progresivo (Trailing Stop) totalmente automático.

- 📲 **Notificaciones por Telegram**  
  Alertas en tiempo real de entradas, salidas y movimientos de SL.

- 🌐 **API REST Local**  
  Servidor FastAPI para consultar datos del order book.

---

## 🛠️ Requisitos

- Python **3.8 o superior**
- Cuenta de **Bybit** con API habilitada
- Bot de **Telegram** (opcional, para notificaciones)

---

## 📦 Instalación

### 1️⃣ Instalar las dependencias

```bash
pip install pybit python-binance websocket-client fastapi uvicorn pyTelegramBotAPI requests joblib scikit-learn
---
