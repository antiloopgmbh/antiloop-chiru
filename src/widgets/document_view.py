import os
import json
import logging
import mimetypes
import urllib.parse
from gi.repository import WebKit, Gtk, GObject, Gio, GLib, Gdk

# Extensions whose default handler on a typical desktop is to execute the
# file outright rather than merely display it (e.g. a .desktop file's
# Exec= line, or an interpreter/binary). Links to these are never launched
# automatically, unlike ordinary documents/images/media which open in
# their normal viewer app.
DANGEROUS_LINK_EXTENSIONS = (
    '.desktop', '.exe', '.msi', '.bat', '.cmd', '.com', '.scr', '.ps1',
    '.vbs', '.vbe', '.jar', '.sh', '.bash', '.zsh', '.command',
    '.appimage', '.bin', '.run',
)

class DocumentView(WebKit.WebView):
    __gsignals__ = {
        'outline-received': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'search-results-updated': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'file-navigation-requested': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'mouse-back-clicked': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'mouse-forward-clicked': (GObject.SignalFlags.RUN_FIRST, None, ())
    }

    def __init__(self):
        settings = WebKit.Settings()
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_allow_universal_access_from_file_urls(True)

        super().__init__(settings=settings)
        self.set_vexpand(True)
        self.set_hexpand(True)

        # Register custom URI scheme
        context = self.get_context()
        context.register_uri_scheme("app-local", self.on_uri_scheme_request)

        # Register script message handlers
        manager = self.get_user_content_manager()
        manager.register_script_message_handler("outline")
        manager.connect("script-message-received::outline", self.on_outline_received)
        manager.register_script_message_handler("search")
        manager.connect("script-message-received::search", self.on_search_received)

        # Navigation policy intercept
        self.connect("decide-policy", self.on_decide_policy)
        self.connect("load-failed", lambda w, e, u, err: print(f"LOAD FAILED: {err.message} ({u})"))
        self.connect("web-process-terminated", lambda w, r: print(f"WEB PROCESS TERMINATED: {r}"))

        # Mouse side button gestures
        self.mouse_gesture = Gtk.GestureClick.new()
        self.mouse_gesture.set_button(0)
        self.mouse_gesture.connect("pressed", self.on_mouse_pressed)
        self.add_controller(self.mouse_gesture)

    def on_uri_scheme_request(self, request, user_data=None):
        uri = request.get_uri()
        parsed = urllib.parse.urlparse(uri)
        path = urllib.parse.unquote(parsed.path)
        if parsed.netloc:
            path = '/' + parsed.netloc + path

        if os.path.exists(path) and os.path.isfile(path):
            try:
                if path.endswith('.js'):
                    mime_type = 'application/javascript'
                elif path.endswith('.css'):
                    mime_type = 'text/css'
                elif path.endswith('.html'):
                    mime_type = 'text/html'
                else:
                    mime_type, _ = mimetypes.guess_type(path)
                    if not mime_type:
                        mime_type = "application/octet-stream"

                with open(path, 'rb') as f:
                    data = f.read()

                stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
                request.finish(stream, len(data), mime_type)
                return
            except Exception as e:
                print(f"Error reading file in URI scheme: {e}")

        # Fallback: return an empty stream to avoid TypeError in WebKitGTK
        empty_stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(b""))
        request.finish(empty_stream, 0, "application/octet-stream")

    def on_outline_received(self, manager, jsc_value):
        try:
            outline_json = jsc_value.to_string()
            self.emit('outline-received', outline_json)
        except Exception as e:
            print(f"Error handling outline script message: {e}")

    def on_search_received(self, manager, jsc_value):
        try:
            search_json = jsc_value.to_string()
            self.emit('search-results-updated', search_json)
        except Exception as e:
            print(f"Error handling search script message: {e}")

    def on_mouse_pressed(self, gesture, n_press, x, y):
        button = gesture.get_current_button()
        if button == 8:
            self.emit('mouse-back-clicked')
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        elif button == 9:
            self.emit('mouse-forward-clicked')
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def on_decide_policy(self, webview, decision, decision_type):
        if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            action = decision.get_navigation_action()
            request = action.get_request()
            uri = request.get_uri()

            if action.is_user_gesture():
                parsed_target = urllib.parse.urlparse(uri)
                current_uri = self.get_uri()

                # Check if it's an internal anchor navigation in the same document
                if current_uri:
                    parsed_current = urllib.parse.urlparse(current_uri)
                    if parsed_current.path == parsed_target.path:
                        # Let WebKit handle internal scrolling
                        return False

                # Otherwise, intercept the navigation
                decision.ignore()
                
                # Handle local file links (both app-local:// and file://)
                if parsed_target.scheme in ("app-local", "file"):
                    file_path = urllib.parse.unquote(parsed_target.path)
                    
                    if file_path.lower().endswith(('.md', '.markdown')):
                        self.emit('file-navigation-requested', file_path)
                    elif file_path.lower().endswith(DANGEROUS_LINK_EXTENSIONS):
                        logging.warning("Refusing to launch potentially executable link target: %s", file_path)
                    else:
                        # Convert to standard file:// URI for launching external viewer
                        file_uri = "file://" + urllib.parse.quote(file_path, safe='/')
                        Gio.AppInfo.launch_default_for_uri(file_uri, None)
                elif parsed_target.scheme in ("http", "https", "mailto"):
                    Gio.AppInfo.launch_default_for_uri(uri, None)
                return True
        return False

    def scroll_to_heading(self, heading_id):
        js = f"document.getElementById({json.dumps(heading_id)}).scrollIntoView({{behavior: 'smooth'}});"
        self.evaluate_javascript(js, -1)
