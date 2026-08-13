import os
import urllib.parse
import json
import logging
from gi.repository import Gtk, Gio, GLib, Pango, Gdk, WebKit
from core.platform import current_platform

from core.history import NavigationHistory
from core.renderer import render_markdown
from widgets.file_sidebar import FileSidebar
from widgets.outline_sidebar import OutlineSidebar
from widgets.document_view import DocumentView
from core.settings import AppSettings

class MarkdownViewerWindow(current_platform.get_base_window_class()):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_default_size(1000, 700)
        self.set_title("Antiloop Chiru")

        self.history = NavigationHistory()
        self.settings = AppSettings()
        self.file_monitor = None
        self.current_zoom = 1.0
        self.scroll_accumulated_dy = 0.0
        self.current_match_index = 0
        self.total_matches = 0

        # Setup main container
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header Bar
        self.header_bar = current_platform.create_header_bar()
        current_platform.setup_window_layout(self, self.main_box, self.header_bar)

        # Search Bar
        self.search_bar = Gtk.SearchBar()
        self.search_bar.set_valign(Gtk.Align.START)
        self.search_bar.set_key_capture_widget(self)

        self.search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.search_box.set_margin_start(12)
        self.search_box.set_margin_end(12)
        self.search_box.set_margin_top(6)
        self.search_box.set_margin_bottom(6)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_hexpand(True)
        self.search_entry.set_placeholder_text("Search in document...")
        self.search_entry.connect("search-changed", self.on_search_changed)
        self.search_entry.connect("stop-search", lambda x: self.hide_search())
        self.search_box.append(self.search_entry)

        self.lbl_search_count = Gtk.Label(label="0/0")
        self.lbl_search_count.set_opacity(0.6)
        self.search_box.append(self.lbl_search_count)

        self.btn_search_prev = Gtk.Button(icon_name="go-up-symbolic")
        self.btn_search_prev.set_tooltip_text("Previous match (Shift+Enter)")
        self.btn_search_prev.connect("clicked", self.on_search_prev)
        self.search_box.append(self.btn_search_prev)

        self.btn_search_next = Gtk.Button(icon_name="go-down-symbolic")
        self.btn_search_next.set_tooltip_text("Next match (Enter)")
        self.btn_search_next.connect("clicked", self.on_search_next)
        self.search_box.append(self.btn_search_next)

        self.btn_search_close = Gtk.Button(icon_name="window-close-symbolic")
        self.btn_search_close.set_tooltip_text("Close search (Esc)")
        self.btn_search_close.connect("clicked", lambda x: self.hide_search())
        self.search_box.append(self.btn_search_close)

        self.search_bar.set_child(self.search_box)
        self.search_bar.connect_entry(self.search_entry)
        self.main_box.append(self.search_bar)

        # Key controller on search entry to capture Enter / Shift+Enter in CAPTURE phase
        search_key_ctrl = Gtk.EventControllerKey.new()
        search_key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        search_key_ctrl.connect("key-pressed", self.on_search_key_pressed)
        self.search_entry.add_controller(search_key_ctrl)

        # Toggle Left Sidebar Button (File browser)
        self.btn_left_sidebar = Gtk.ToggleButton(icon_name="sidebar-show-symbolic")
        self.btn_left_sidebar.set_tooltip_text("Toggle file sidebar")
        self.btn_left_sidebar.connect("toggled", self.toggle_left_sidebar)
        self.header_bar.pack_start(self.btn_left_sidebar)

        # Separator on left side between sidebar toggle and file actions
        sep_left = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep_left.set_margin_top(8)
        sep_left.set_margin_bottom(8)
        self.header_bar.pack_start(sep_left)

        # Open Button
        self.btn_open = Gtk.Button(icon_name="document-open-symbolic")
        self.btn_open.set_tooltip_text("Open markdown file")
        self.btn_open.connect("clicked", lambda x: self.show_file_chooser())
        self.header_bar.pack_start(self.btn_open)

        # Recent Files MenuButton
        self.btn_recents = Gtk.MenuButton(icon_name="document-open-recent-symbolic")
        self.btn_recents.set_tooltip_text("Recent Files")
        
        self.recents_popover = Gtk.Popover()
        self.recents_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.recents_box.set_margin_start(6)
        self.recents_box.set_margin_end(6)
        self.recents_box.set_margin_top(6)
        self.recents_box.set_margin_bottom(6)
        
        title_lbl = Gtk.Label(xalign=0.0)
        title_lbl.set_markup("<b>Recent Files</b>")
        title_lbl.set_margin_start(6)
        title_lbl.set_margin_bottom(6)
        self.recents_box.append(title_lbl)
        
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_bottom(4)
        self.recents_box.append(sep)

        self.recents_list = Gtk.ListBox()
        self.recents_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.recents_list.connect("row-activated", self.on_recent_file_activated)
        self.recents_box.append(self.recents_list)
        
        self.recents_popover.set_child(self.recents_box)
        self.btn_recents.set_popover(self.recents_popover)
        self.recents_popover.connect("notify::visible", self.update_recents_menu)
        
        self.header_bar.pack_start(self.btn_recents)

        # Toggle Right Sidebar Button (Outline)
        self.btn_right_sidebar = Gtk.ToggleButton(icon_name="sidebar-show-right-symbolic")
        self.btn_right_sidebar.set_tooltip_text("Toggle outline sidebar")
        self.btn_right_sidebar.connect("toggled", self.toggle_right_sidebar)
        self.header_bar.pack_end(self.btn_right_sidebar)

        # Separator on right side between sidebar toggle and document actions
        sep_right = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep_right.set_margin_top(8)
        sep_right.set_margin_bottom(8)
        self.header_bar.pack_end(sep_right)

        # Print Button
        self.btn_print = Gtk.Button(icon_name="document-print-symbolic")
        self.btn_print.set_tooltip_text("Print Document (Ctrl+P)")
        self.btn_print.connect("clicked", lambda x: self.print_document())
        self.btn_print.set_sensitive(False)
        self.header_bar.pack_end(self.btn_print)

        # Find (Search) Button
        self.btn_find = Gtk.ToggleButton(icon_name="edit-find-symbolic")
        self.btn_find.set_tooltip_text("Search in document (Ctrl+F)")
        self.btn_find.connect("toggled", self.on_btn_find_toggled)
        self.btn_find.set_sensitive(False)
        self.header_bar.pack_end(self.btn_find)

        # Reset Zoom Container
        self.zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.zoom_box.set_valign(Gtk.Align.CENTER)
        self.zoom_box.set_visible(False)

        self.lbl_zoom_factor = Gtk.Label(label="100%")
        self.lbl_zoom_factor.set_opacity(0.6)
        self.zoom_box.append(self.lbl_zoom_factor)

        self.btn_zoom_reset = Gtk.Button(label="Reset")
        self.btn_zoom_reset.set_tooltip_text("Reset zoom to 100% (Ctrl+0)")
        self.btn_zoom_reset.connect("clicked", lambda x: self.zoom_reset())
        self.zoom_box.append(self.btn_zoom_reset)
        self.header_bar.pack_end(self.zoom_box)

        # Navigation box (Back / Forward)
        self.nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.nav_box.add_css_class("linked")
        self.btn_back = Gtk.Button(icon_name="go-previous-symbolic")
        self.btn_back.set_tooltip_text("Go back")
        self.btn_back.set_sensitive(False)
        self.btn_back.connect("clicked", lambda x: self.go_back())
        self.btn_forward = Gtk.Button(icon_name="go-next-symbolic")
        self.btn_forward.set_tooltip_text("Go forward")
        self.btn_forward.set_sensitive(False)
        self.btn_forward.connect("clicked", lambda x: self.go_forward())
        self.nav_box.append(self.btn_back)
        self.nav_box.append(self.btn_forward)
        self.header_bar.pack_end(self.nav_box)

        # Outer Paned (Left Sidebar + Inner Area)
        self.left_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.left_paned.set_vexpand(True)
        self.left_paned.set_hexpand(True)
        self.left_paned.set_position(240)
        self.left_paned.set_resize_start_child(False)
        self.left_paned.set_shrink_start_child(False)
        self.left_paned.set_resize_end_child(True)
        self.main_box.append(self.left_paned)

        # Left Sidebar (File browser)
        self.file_sidebar = FileSidebar()
        self.file_sidebar.connect("file-activated", self.on_file_activated)
        self.left_paned.set_start_child(self.file_sidebar)

        # Inner Paned (Main Content + Right Sidebar)
        self.right_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.right_paned.set_vexpand(True)
        self.right_paned.set_hexpand(True)
        self.right_paned.set_position(520)
        self.right_paned.set_resize_start_child(True)
        self.right_paned.set_resize_end_child(False)
        self.right_paned.set_shrink_start_child(False)
        self.right_paned.set_shrink_end_child(False)
        self.left_paned.set_end_child(self.right_paned)

        # Main Content: WebView wrapper to intercept capture-phase scroll events
        self.webview_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.webview_container.set_vexpand(True)
        self.webview_container.set_hexpand(True)

        self.webview = DocumentView()
        self.webview.set_vexpand(True)
        self.webview.set_hexpand(True)
        self.webview.connect("outline-received", self.on_outline_received)
        self.webview.connect("search-results-updated", self.on_search_results_updated)
        self.webview.connect("file-navigation-requested", self.on_file_navigation_requested)
        self.webview.connect("mouse-back-clicked", lambda w: self.go_back())
        self.webview.connect("mouse-forward-clicked", lambda w: self.go_forward())
        
        self.webview_container.append(self.webview)
        self.webview.set_visible(True)
        self.webview_container.set_visible(True)
        self.right_paned.set_start_child(self.webview_container)

        # Scroll controller on the container (running in CAPTURE phase to intercept before WebKit receives it)
        scroll_controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        scroll_controller.connect("scroll", self.on_webview_scroll)
        self.webview_container.add_controller(scroll_controller)

        # Window-level key event controller to capture Escape key and close search
        win_key_ctrl = Gtk.EventControllerKey.new()
        win_key_ctrl.connect("key-pressed", self.on_window_key_pressed)
        self.add_controller(win_key_ctrl)

        # Right Sidebar (Outline)
        self.outline_sidebar = OutlineSidebar()
        self.outline_sidebar.connect("heading-activated", self.on_heading_activated)
        self.right_paned.set_end_child(self.outline_sidebar)

        # Dark mode listener
        current_platform.init_theme_monitoring(self, self.on_theme_changed)

        # Keyboard shortcuts actions
        action_open = Gio.SimpleAction.new("open", None)
        action_open.connect("activate", lambda a, p: self.show_file_chooser())
        self.add_action(action_open)

        action_close_doc = Gio.SimpleAction.new("close_document", None)
        action_close_doc.connect("activate", lambda a, p: self.close_document())
        self.add_action(action_close_doc)

        action_zoom_in = Gio.SimpleAction.new("zoom_in", None)
        action_zoom_in.connect("activate", lambda a, p: self.zoom_in())
        self.add_action(action_zoom_in)

        action_zoom_out = Gio.SimpleAction.new("zoom_out", None)
        action_zoom_out.connect("activate", lambda a, p: self.zoom_out())
        self.add_action(action_zoom_out)

        action_zoom_reset = Gio.SimpleAction.new("zoom_reset", None)
        action_zoom_reset.connect("activate", lambda a, p: self.zoom_reset())
        self.add_action(action_zoom_reset)

        action_find = Gio.SimpleAction.new("find", None)
        action_find.connect("activate", lambda a, p: self.show_search())
        self.add_action(action_find)

        action_print = Gio.SimpleAction.new("print", None)
        action_print.connect("activate", lambda a, p: self.print_document())
        self.add_action(action_print)

        self.show_placeholder()

    def is_dark_mode(self):
        return current_platform.is_dark_mode(self)

    def show_placeholder(self):
        is_dark = self.is_dark_mode()
        bg_color = "#1e1e1e" if is_dark else "#fafafa"
        fg_color = "#aaaaaa" if is_dark else "#666666"
        placeholder_html = f"""<html><body style='font-family:sans-serif; text-align:center; padding-top:100px; color:{fg_color}; background-color:{bg_color};'>
            <h2 style='margin-bottom:8px;'>No Markdown File Open</h2>
            <p style='margin-top:0;'>Select a file using the Open button.</p>
        </body></html>"""
        self.webview.load_html(placeholder_html, None)
        self.file_sidebar.set_visible(False)
        self.outline_sidebar.set_visible(False)
        self.btn_left_sidebar.set_active(False)
        self.btn_right_sidebar.set_active(False)
        self.btn_left_sidebar.set_sensitive(False)
        self.btn_right_sidebar.set_sensitive(False)
        self.btn_print.set_sensitive(False)
        self.btn_find.set_sensitive(False)
        self.btn_find.set_active(False)
        self.hide_search()

    def close_document(self):
        if self.file_monitor:
            self.file_monitor.cancel()
            self.file_monitor = None
        self.history = NavigationHistory()
        self.settings.last_opened_filepath = None
        self.show_placeholder()

    def open_file(self, filepath, save_to_history=True, is_explicit=False, scroll_x=0, scroll_y=0):
        filepath = os.path.abspath(filepath)
        if filepath.startswith("/run/user/"):
            filepath = self.resolve_portal_path(filepath)
        logging.debug("Opening filepath: %s", filepath)
        if not os.path.exists(filepath):
            return

        # Cancel previous monitor if any
        if self.file_monitor:
            self.file_monitor.cancel()
            self.file_monitor = None

        # Setup file monitor for reload on change
        gio_file = Gio.File.new_for_path(filepath)
        try:
            self.file_monitor = gio_file.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self.file_monitor.connect("changed", self.on_file_changed_on_disk)
        except Exception as e:
            print("Failed to monitor file:", e)

        self.history.open_file(filepath, save_to_history=save_to_history)
        
        # Always update last opened filepath to restore on next startup
        self.settings.last_opened_filepath = filepath
        
        # Add to recents if explicitly opened or navigated (not on back/forward history navigation)
        if is_explicit or save_to_history:
            self.settings.add_recent_file(filepath)

        self.btn_back.set_sensitive(self.history.can_go_back())
        self.btn_forward.set_sensitive(self.history.can_go_forward())

        self.set_title(f"{os.path.basename(filepath)} - Antiloop Chiru")

        self.btn_left_sidebar.set_sensitive(True)
        self.btn_right_sidebar.set_sensitive(True)
        self.btn_print.set_sensitive(True)
        self.btn_find.set_sensitive(True)
        self.btn_left_sidebar.set_active(self.settings.show_left_sidebar)
        self.btn_right_sidebar.set_active(self.settings.show_right_sidebar)
        self.file_sidebar.set_visible(self.settings.show_left_sidebar)
        self.outline_sidebar.set_visible(self.settings.show_right_sidebar)

        if self.settings.show_left_sidebar:
            self.left_paned.set_position(240)
        if self.settings.show_right_sidebar:
            width = self.right_paned.get_width()
            if width > 300:
                self.right_paned.set_position(width - 240)

        self.file_sidebar.load_directory(filepath)
        self.outline_sidebar.set_filename(filepath)

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                md_content = f.read()
        except Exception as e:
            md_content = f"# Error\nFailed to read file: {e}"

        # Render HTML using our rendering logic
        is_dark = self.is_dark_mode()
        script_dir = os.path.dirname(os.path.abspath(__file__))
        assets_dir = os.path.join(script_dir, "assets")
        
        html = render_markdown(md_content, is_dark, assets_dir, scroll_x=scroll_x, scroll_y=scroll_y)
        parent_dir = os.path.dirname(filepath)
        base_uri = "file://" + urllib.parse.quote(parent_dir, safe='/') + "/"
        self.webview.load_html(html, base_uri)
        self.webview.set_zoom_level(self.current_zoom)

    def go_back(self):
        prev_file = self.history.go_back()
        if prev_file:
            self.btn_back.set_sensitive(self.history.can_go_back())
            self.btn_forward.set_sensitive(self.history.can_go_forward())
            self.open_file(prev_file, save_to_history=False)

    def go_forward(self):
        next_file = self.history.go_forward()
        if next_file:
            self.btn_back.set_sensitive(self.history.can_go_back())
            self.btn_forward.set_sensitive(self.history.can_go_forward())
            self.open_file(next_file, save_to_history=False)

    def on_file_activated(self, sidebar, filepath):
        self.open_file(filepath, save_to_history=True, is_explicit=False)

    def on_file_navigation_requested(self, webview, filepath):
        self.open_file(filepath, save_to_history=True)

    def on_heading_activated(self, sidebar, heading_id):
        self.webview.scroll_to_heading(heading_id)

    def on_outline_received(self, webview, outline_json_str):
        self.outline_sidebar.populate(outline_json_str)

    def toggle_left_sidebar(self, btn):
        active = btn.get_active()
        self.file_sidebar.set_visible(active)
        if active:
            self.left_paned.set_position(240)
        if self.history.current_filepath:
            self.settings.show_left_sidebar = active

    def toggle_right_sidebar(self, btn):
        active = btn.get_active()
        self.outline_sidebar.set_visible(active)
        if active:
            width = self.right_paned.get_width()
            if width > 300:
                self.right_paned.set_position(width - 240)
            else:
                self.right_paned.set_position(520)
        if self.history.current_filepath:
            self.settings.show_right_sidebar = active

    def on_recent_file_activated(self, list_box, row):
        if row and hasattr(row, 'filepath'):
            self.recents_popover.popdown()
            self.open_file(row.filepath, save_to_history=True, is_explicit=True)

    def update_recents_menu(self, popover, gspec):
        if not popover.get_visible():
            return
            
        # Clear old rows
        while True:
            row = self.recents_list.get_row_at_index(0)
            if not row:
                break
            self.recents_list.remove(row)
            
        recent_files = self.settings.recent_files
        if not recent_files:
            no_recents_lbl = Gtk.Label(label="No recent files", xalign=0.0)
            no_recents_lbl.set_margin_start(6)
            no_recents_lbl.set_margin_end(6)
            no_recents_lbl.set_margin_top(8)
            no_recents_lbl.set_margin_bottom(8)
            
            row = Gtk.ListBoxRow()
            row.set_child(no_recents_lbl)
            row.set_selectable(False)
            row.set_activatable(False)
            self.recents_list.append(row)
            return

        for filepath in recent_files:
            filename = os.path.basename(filepath)
            dir_path = os.path.dirname(filepath)
            
            row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            row_box.set_margin_top(6)
            row_box.set_margin_bottom(6)
            
            lbl_name = Gtk.Label(xalign=0.0)
            lbl_name.set_markup(f"<b>{GLib.markup_escape_text(filename)}</b>")
            
            lbl_dir = Gtk.Label(label=dir_path, xalign=0.0)
            lbl_dir.add_css_class("dim-label")
            lbl_dir.set_opacity(0.6)
            lbl_dir.set_ellipsize(Pango.EllipsizeMode.START)
            lbl_dir.set_max_width_chars(40)
            
            row_box.append(lbl_name)
            row_box.append(lbl_dir)
            
            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            row.filepath = filepath
            self.recents_list.append(row)

    def on_theme_changed(self, manager, gspec):
        if self.history.current_filepath:
            self.reload_current_file()
        else:
            self.show_placeholder()

    def on_file_changed_on_disk(self, monitor, file, other_file, event_type):
        if event_type in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CHANGED):
            GLib.idle_add(self.reload_current_file)

    def reload_current_file(self):
        if not (self.history.current_filepath and os.path.exists(self.history.current_filepath)):
            return False

        if getattr(self, "_reloading_file", False):
            return False
        self._reloading_file = True

        def on_scroll_retrieved(webview, result, user_data=None):
            scroll_x, scroll_y = 0, 0
            try:
                val = webview.evaluate_javascript_finish(result)
                if val:
                    json_str = val.to_string()
                    data = json.loads(json_str)
                    scroll_x = data.get("x", 0)
                    scroll_y = data.get("y", 0)
            except Exception as e:
                print("Error getting scroll position:", e)

            try:
                if self.history.current_filepath and os.path.exists(self.history.current_filepath):
                    self.open_file(self.history.current_filepath, save_to_history=False, is_explicit=False, scroll_x=scroll_x, scroll_y=scroll_y)
            finally:
                self._reloading_file = False

        try:
            self.webview.evaluate_javascript(
                "JSON.stringify({x: window.scrollX, y: window.scrollY})",
                -1, None, None, None, on_scroll_retrieved, None
            )
        except Exception as e:
            print("Error evaluating javascript for scroll position:", e)
            self._reloading_file = False
            if self.history.current_filepath and os.path.exists(self.history.current_filepath):
                self.open_file(self.history.current_filepath, save_to_history=False, is_explicit=False)

        return False

    def on_webview_scroll(self, controller, dx, dy):
        state = controller.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK:
            self.scroll_accumulated_dy += dy
            
            # Reset accumulator if scroll direction changes
            if (dy > 0 and self.scroll_accumulated_dy < 0) or (dy < 0 and self.scroll_accumulated_dy > 0):
                self.scroll_accumulated_dy = dy

            # Trigger zoom step for each full unit (1.0) accumulated
            while self.scroll_accumulated_dy <= -1.0:
                self.zoom_in()
                self.scroll_accumulated_dy += 1.0
            while self.scroll_accumulated_dy >= 1.0:
                self.zoom_out()
                self.scroll_accumulated_dy -= 1.0
            return True
        else:
            self.scroll_accumulated_dy = 0.0
            return False

    def zoom_in(self):
        self.set_zoom_factor(self.current_zoom + 0.1)

    def zoom_out(self):
        self.set_zoom_factor(self.current_zoom - 0.1)

    def zoom_reset(self):
        self.set_zoom_factor(1.0)

    def set_zoom_factor(self, factor):
        factor = max(0.5, min(3.0, factor))
        factor = round(factor, 2)
        self.current_zoom = factor
        self.webview.set_zoom_level(factor)
        
        if abs(factor - 1.0) < 0.01:
            self.zoom_box.set_visible(False)
        else:
            percent = int(factor * 100)
            self.lbl_zoom_factor.set_text(f"{percent}%")
            self.zoom_box.set_visible(True)

    def do_destroy(self):
        if self.file_monitor:
            self.file_monitor.cancel()
            self.file_monitor = None
        current_platform.get_base_window_class().do_destroy(self)

    def resolve_portal_path(self, filepath):
        # Try to read FUSE extended attribute 'user.document-portal.host-path'
        try:
            host_path_bytes = os.getxattr(filepath, 'user.document-portal.host-path')
            host_path = host_path_bytes.decode('utf-8')
            if os.path.exists(host_path):
                return host_path
        except Exception as e:
            print("Failed to resolve portal path via FUSE xattr:", e)
        return filepath

    def show_file_chooser(self):
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Open Markdown File")
        
        if self.history.current_filepath:
            parent_dir = os.path.dirname(self.history.current_filepath)
            initial_folder_file = Gio.File.new_for_path(parent_dir)
            dialog.set_initial_folder(initial_folder_file)
        
        filters = Gio.ListStore.new(Gtk.FileFilter)
        
        filter_md = Gtk.FileFilter.new()
        filter_md.set_name("Markdown files")
        filter_md.add_suffix("md")
        filter_md.add_suffix("markdown")
        filters.append(filter_md)
        
        filter_all = Gtk.FileFilter.new()
        filter_all.set_name("All files")
        filter_all.add_pattern("*")
        filters.append(filter_all)
        
        dialog.set_filters(filters)
        dialog.set_default_filter(filter_md)
        dialog.open(self, None, self.on_file_dialog_open_callback)

    def on_file_dialog_open_callback(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                self.open_file(file.get_path(), save_to_history=True, is_explicit=True)
        except Exception as e:
            print(f"Error selecting file: {e}")

    # --- Search and Find Functions ---
    def on_btn_find_toggled(self, btn):
        active = btn.get_active()
        if active:
            self.show_search()
        else:
            self.hide_search()

    def show_search(self):
        if not self.history.current_filepath:
            self.btn_find.set_active(False)
            return
        self.search_bar.set_search_mode(True)
        self.search_entry.grab_focus()
        if not self.btn_find.get_active():
            self.btn_find.set_active(True)

    def hide_search(self):
        self.search_bar.set_search_mode(False)
        self.webview.evaluate_javascript("if (window.clearSearchHighlights) { window.clearSearchHighlights(); }", -1)
        self.webview.grab_focus()
        if self.btn_find.get_active():
            self.btn_find.set_active(False)

    def on_search_changed(self, entry):
        text = entry.get_text()
        if not text:
            self.webview.evaluate_javascript("if (window.clearSearchHighlights) { window.clearSearchHighlights(); }", -1)
        else:
            js = f"window.highlightAll({json.dumps(text)});"
            self.webview.evaluate_javascript(js, -1)

    def on_search_next(self, *args):
        self.webview.evaluate_javascript("window.nextSearchMatch();", -1)

    def on_search_prev(self, *args):
        self.webview.evaluate_javascript("window.prevSearchMatch();", -1)

    def on_search_key_pressed(self, controller, keyval, keycode, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if state & Gdk.ModifierType.SHIFT_MASK:
                self.on_search_prev()
                return True
            else:
                self.on_search_next()
                return True
        return False

    def on_window_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            if self.search_bar.get_search_mode():
                self.hide_search()
                return True
        return False

    def on_search_results_updated(self, webview, result_json):
        try:
            data = json.loads(result_json)
            self.current_match_index = data.get("current", 0)
            self.total_matches = data.get("total", 0)
            self.update_search_label()
        except Exception as e:
            print(f"Error parsing search results JSON: {e}")

    def update_search_label(self):
        if self.total_matches > 0:
            self.lbl_search_count.set_text(f"{self.current_match_index}/{self.total_matches}")
        else:
            self.lbl_search_count.set_text("0/0")

    # --- Print Functions ---
    def print_document(self):
        try:
            if self.history.current_filepath:
                original_zoom = self.current_zoom
                if original_zoom != 1.0:
                    self.webview.set_zoom_level(1.0)

                print_op = WebKit.PrintOperation.new(self.webview)
                
                # Restore original zoom level only after printing actually finishes
                def on_print_finished(op):
                    if original_zoom != 1.0:
                        self.webview.set_zoom_level(original_zoom)
                print_op.connect("finished", on_print_finished)

                # Set 2.0 cm (20mm) margins on the PageSetup
                page_setup = Gtk.PageSetup.new()
                page_setup.set_top_margin(20.0, Gtk.Unit.MM)
                page_setup.set_bottom_margin(20.0, Gtk.Unit.MM)
                page_setup.set_left_margin(20.0, Gtk.Unit.MM)
                page_setup.set_right_margin(20.0, Gtk.Unit.MM)
                print_op.set_page_setup(page_setup)

                settings = Gtk.PrintSettings.new()
                filename = os.path.basename(self.history.current_filepath)
                settings.set("job-name", f"Antiloop Chiru - {filename}")
                print_op.set_print_settings(settings)
                print_op.run_dialog(self)
        except Exception as e:
            import traceback
            traceback.print_exc()
