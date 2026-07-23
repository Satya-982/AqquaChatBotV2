import threading
import time
import webview

from app import app


def run_flask():
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    time.sleep(2)

    webview.create_window(
        "AquaBot",
        "http://127.0.0.1:5000",
        width=1400,
        height=900
    )

    webview.start()