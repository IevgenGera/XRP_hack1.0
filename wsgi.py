from app import app, socketio, start_xrpl_thread, logger

# Start XRPL listener thread when app is initialized through WSGI
logger.info("Starting XRPL listener thread from WSGI entry point")
start_xrpl_thread()

if __name__ == '__main__':
    socketio.run(app)
