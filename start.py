"""
Launch script for LearnPath for Schools.

Starts the FastAPI server and automatically opens the application in your default
web browser (Chrome, Edge, Firefox, etc.).
"""
import sys
import time
import threading
import webbrowser

def open_browser():
    """Wait 1.5 seconds for the server to bind, then open the browser."""
    time.sleep(1.5)
    url = "http://localhost:8000"
    print(f"\n[LearnPath] Opening browser at {url} ...\n")
    webbrowser.open(url)

if __name__ == "__main__":
    # Start browser opener in background thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Start FastAPI server
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
