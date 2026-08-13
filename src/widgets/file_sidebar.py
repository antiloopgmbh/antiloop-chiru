import os
from gi.repository import Gtk, GObject, Pango, GLib, Gio

class FileSidebar(Gtk.Box):
    __gsignals__ = {
        'file-activated': (GObject.SignalFlags.RUN_FIRST, None, (str,))
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_size_request(240, -1)
        self.current_dir = None
        self.current_active_file = None
        self.dir_monitor = None

        # Header Box
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_margin_start(12)
        header_box.set_margin_end(12)
        header_box.set_margin_top(12)
        header_box.set_margin_bottom(8)

        # Up Button (Go one directory up)
        self.btn_up = Gtk.Button(icon_name="go-up-symbolic")
        self.btn_up.set_has_frame(False)
        self.btn_up.set_tooltip_text("Go up one directory")
        self.btn_up.connect("clicked", self.on_btn_up_clicked)
        header_box.append(self.btn_up)

        # Folder Icon
        icon = Gtk.Image.new_from_icon_name("folder-symbolic")
        header_box.append(icon)

        # Folder Name Label
        self.title_label = Gtk.Label(xalign=0.0)
        self.title_label.set_hexpand(True)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.set_markup("<b>Folder</b>")
        header_box.append(self.title_label)

        self.append(header_box)

        # Separator Line
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.append(separator)

        # ScrolledWindow for ListBox
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self.append(scroll)

        self.list_box = Gtk.ListBox()
        self.list_box.connect("row-activated", self.on_row_activated)
        scroll.set_child(self.list_box)
        self.connect("destroy", self.on_destroy)

    def on_row_activated(self, list_box, row):
        if row and not getattr(row, 'is_placeholder', False) and hasattr(row, 'path'):
            if row.is_folder:
                # Navigate inside the folder
                self.load_directory(row.path, current_filepath=self.current_active_file)
            else:
                # Open the markdown file
                self.emit('file-activated', row.path)

    def on_btn_up_clicked(self, btn):
        if self.current_dir and self.current_dir != "/":
            parent_dir = os.path.dirname(self.current_dir)
            self.load_directory(parent_dir, current_filepath=self.current_active_file)

    def load_directory(self, path, current_filepath=None):
        # Determine path and file
        if os.path.isfile(path):
            dir_path = os.path.dirname(os.path.abspath(path))
            self.current_active_file = os.path.abspath(path)
        else:
            dir_path = os.path.abspath(path)
            if current_filepath:
                self.current_active_file = os.path.abspath(current_filepath)

        self.current_dir = dir_path

        # Setup directory monitor
        if self.dir_monitor:
            self.dir_monitor.cancel()
            self.dir_monitor = None

        gio_dir = Gio.File.new_for_path(dir_path)
        try:
            self.dir_monitor = gio_dir.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self.dir_monitor.connect("changed", self.on_dir_changed_on_disk)
        except Exception as e:
            print("Failed to monitor directory:", e)

        self._populate_list()

    def _populate_list(self):
        dir_path = self.current_dir
        if not dir_path or not os.path.exists(dir_path):
            return

        # Clear list box
        while True:
            row = self.list_box.get_row_at_index(0)
            if not row:
                break
            self.list_box.remove(row)

        # Set dynamic folder title and full path tooltip
        folder_name = os.path.basename(dir_path) or dir_path
        escaped_folder_name = GLib.markup_escape_text(folder_name)
        self.title_label.set_markup(f"<b>{escaped_folder_name}</b>")
        self.title_label.set_tooltip_text(dir_path)

        # Enable/Disable Up button
        self.btn_up.set_sensitive(dir_path != "/")

        try:
            items = os.listdir(dir_path)
        except Exception as e:
            print(f"Error loading directory {dir_path}: {e}")
            return

        # Segregate files and folders
        folders = []
        md_files = []

        for item in items:
            if item.startswith('.'):
                continue
            full_path = os.path.join(dir_path, item)
            try:
                if os.path.isdir(full_path):
                    folders.append((item, full_path))
                elif item.lower().endswith(('.md', '.markdown')):
                    md_files.append((item, full_path))
            except Exception:
                continue

        # Sort alphabetically
        folders.sort(key=lambda x: x[0].lower())
        md_files.sort(key=lambda x: x[0].lower())

        # Show empty folder placeholder
        if not folders and not md_files:
            row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            row_box.set_margin_top(48)
            row_box.set_margin_bottom(48)
            row_box.set_halign(Gtk.Align.CENTER)
            row_box.set_valign(Gtk.Align.CENTER)

            icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
            icon.set_pixel_size(32)
            icon.set_opacity(0.4)
            row_box.append(icon)

            label = Gtk.Label(label="No Markdown files found")
            label.add_css_class("dim-label")
            label.set_opacity(0.6)
            row_box.append(label)

            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            row.set_selectable(False)
            row.set_activatable(False)
            row.is_placeholder = True
            self.list_box.append(row)
            return

        # Render folders first
        for name, full_path in folders:
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row_box.set_margin_start(12)
            row_box.set_margin_end(12)
            row_box.set_margin_top(6)
            row_box.set_margin_bottom(6)

            icon = Gtk.Image.new_from_icon_name("folder-symbolic")
            label = Gtk.Label(label=name, xalign=0.0)
            row_box.append(icon)
            row_box.append(label)

            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            row.path = full_path
            row.is_folder = True
            self.list_box.append(row)

        # Render markdown files
        for name, full_path in md_files:
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row_box.set_margin_start(12)
            row_box.set_margin_end(12)
            row_box.set_margin_top(6)
            row_box.set_margin_bottom(6)

            icon = Gtk.Image.new_from_icon_name("text-x-generic-symbolic")
            label = Gtk.Label(label=name, xalign=0.0)
            row_box.append(icon)
            row_box.append(label)

            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            row.path = full_path
            row.is_folder = False
            self.list_box.append(row)

            # Highlight currently active file
            if self.current_active_file and os.path.abspath(full_path) == self.current_active_file:
                self.list_box.select_row(row)

    def on_dir_changed_on_disk(self, monitor, file, other_file, event_type):
        if event_type in (Gio.FileMonitorEvent.CREATED, Gio.FileMonitorEvent.DELETED, Gio.FileMonitorEvent.CHANGES_DONE_HINT):
            GLib.idle_add(self.reload_directory_list)

    def reload_directory_list(self):
        self._populate_list()
        return False

    def on_destroy(self, widget):
        if self.dir_monitor:
            self.dir_monitor.cancel()
            self.dir_monitor = None
