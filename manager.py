#!/usr/bin/env python
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime, timedelta
from bs4 import BeautifulSoup # type: ignore
import requests
import threading
from queue import Queue
from collections import defaultdict


class BookmarkManager:
    def __init__(self, root):
        self.root = root
        self.soup = None
        self.file_path = None
        self.log_box = None
        self.status_labels = {}
        self.invalid_bookmarks = []
        self.duplicate_bookmarks = []
        self.lock = threading.Lock()
        self.threads = []
        self.is_running = False
        self.setup_ui()

    def setup_ui(self):
        self.root.title("Bookmark Manager")
        self.root.geometry("500x500")

        tk.Button(self.root, text="Load Bookmarks", command=self.load_bookmarks).pack(fill="x", padx=5, pady=5)
        # tk.Button(self.root, text="Remove Old Bookmarks", command=lambda: self.process_bookmarks("remove_old")).pack(fill="x", padx=5, pady=5)
        tk.Button(self.root, text="Check Validity", command=lambda: self.process_bookmarks("check_validity")).pack(fill="x", padx=5, pady=5)
        tk.Button(self.root, text="Find Duplicates", command=lambda: self.process_bookmarks("find_duplicates")).pack(fill="x", padx=5, pady=5)
        tk.Button(self.root, text="Save Bookmarks", command=lambda: self.process_bookmarks("save")).pack(fill="x", padx=5, pady=5)
        tk.Button(self.root, text="Exit", command=self.safe_exit).pack(fill="x", padx=5, pady=5)

        # Status display
        self.status_labels["checked"] = tk.Label(self.root, text="Checked: 0")
        self.status_labels["checked"].pack(anchor="w", padx=5)
        self.status_labels["valid"] = tk.Label(self.root, text="Valid: 0")
        self.status_labels["valid"].pack(anchor="w", padx=5)
        self.status_labels["invalid"] = tk.Label(self.root, text="Invalid: 0")
        self.status_labels["invalid"].pack(anchor="w", padx=5)
        self.status_labels["pending"] = tk.Label(self.root, text="Pending: 0")
        self.status_labels["pending"].pack(anchor="w", padx=5)

        # Log display
        self.log_box = tk.Text(self.root, wrap="word", height=10)
        self.log_box.pack(fill="both", expand=True, padx=5, pady=5)

    def log(self, message):
        """Log message to UI text box"""
        with self.lock:
            self.log_box.insert("end", f"{message}\n")
            self.log_box.see("end")

    def load_bookmarks(self):
        """Load bookmarks file"""
        if self.is_running:
            messagebox.showwarning("Warning", "Operation in progress, please wait!")
            return
        file_path = filedialog.askopenfilename(title="Select Bookmarks HTML File", filetypes=[("HTML files", "*.html")])
        if not file_path:
            self.log("No file selected.")
            return
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                self.soup = BeautifulSoup(file, "html.parser")
                self.file_path = file_path
                self.log(f"Successfully loaded bookmarks file: {file_path}")
        except Exception as e:
            self.log(f"Error loading file: {e}")

    def update_status(self, checked, valid, invalid, total):
        """Update status display"""
        with self.lock:
            self.status_labels["checked"].config(text=f"Checked: {checked}")
            self.status_labels["valid"].config(text=f"Valid: {valid}")
            self.status_labels["invalid"].config(text=f"Invalid: {invalid}")
            self.status_labels["pending"].config(text=f"Pending: {total - checked}")

    def get_bookmark_path(self, a_tag):
        """Get complete path of bookmark"""
        path = []
        parent = a_tag.parent
        while parent and parent.name:
            if parent.name == "dl":
                folder = parent.find_previous_sibling("h3")
                if folder:
                    path.append(folder.text.strip())
            parent = parent.parent
        return " > ".join(reversed(path))

    def check_bookmark_validity(self):
        """Check bookmark validity (multi-threaded)"""
        if self.is_running:
            messagebox.showwarning("Warning", "Operation in progress, please wait!")
            return
        if not self.soup:
            self.log("Please load a bookmarks file first!")
            return

        self.is_running = True
        self.invalid_bookmarks = []
        bookmarks = []
        
        # Collect all bookmarks and their paths
        for a_tag in self.soup.find_all("a"):
            path = self.get_bookmark_path(a_tag)
            bookmarks.append((a_tag, path))
            
        total = len(bookmarks)
        checked, valid, invalid = 0, 0, 0

        def worker(queue):
            nonlocal checked, valid, invalid
            while not queue.empty():
                a_tag, path = queue.get()
                href = a_tag.get("href")
                try:
                    response = requests.head(href, timeout=5)
                    if response.status_code < 400:
                        valid += 1
                    else:
                        invalid += 1
                        self.invalid_bookmarks.append((a_tag, path))
                except:
                    invalid += 1
                    self.invalid_bookmarks.append((a_tag, path))

                checked += 1
                self.update_status(checked, valid, invalid, total)
                location = f" (Location: {path})" if path else ""
                self.log(f"Checking bookmark: {href}{location}")
                queue.task_done()

        queue = Queue()
        for bookmark in bookmarks:
            queue.put(bookmark)

        # Create threads
        for _ in range(10):
            thread = threading.Thread(target=worker, args=(queue,), daemon=True)
            self.threads.append(thread)
            thread.start()

        def on_complete():
            queue.join()
            self.is_running = False
            self.log("Check completed!")
            if self.invalid_bookmarks:
                self.ask_delete_invalid_bookmarks()

        threading.Thread(target=on_complete, daemon=True).start()

    def ask_delete_invalid_bookmarks(self):
        """Ask user whether to delete invalid bookmarks"""
        invalid_count = len(self.invalid_bookmarks)
        message = f"Check completed, found {invalid_count} invalid bookmarks:\n\n"
        for _, path in self.invalid_bookmarks[:10]:
            message += f"- Location: {path}\n"
        if invalid_count > 10:
            message += f"\n... and {invalid_count - 10} more\n"
        message += "\nDelete these invalid bookmarks?"
        
        if messagebox.askyesno("Invalid Bookmarks", message):
            for a_tag, _ in self.invalid_bookmarks:
                a_tag.decompose()
            self.log(f"Deleted {invalid_count} invalid bookmarks!")

    def safe_exit(self):
        """Safe exit, terminate all threads"""
        if self.is_running:
            messagebox.showwarning("Warning", "Operation in progress, please wait!")
            return
        self.root.quit()

    def find_duplicate_bookmarks(self):
        """Find duplicate bookmarks and ask whether to delete (considering folder structure)"""
        if self.is_running:
            messagebox.showwarning("Warning", "Operation in progress, please wait!")
            return
        if not self.soup:
            self.log("Please load a bookmarks file first!")
            return

        self.is_running = True
        self.duplicate_bookmarks = []
        bookmarks = defaultdict(list)

        # Collect all bookmarks with their path information
        for a_tag in self.soup.find_all("a"):
            title = a_tag.text.strip()
            href = a_tag.get("href")
            path = self.get_bookmark_path(a_tag)
            bookmarks[(title, href)].append((a_tag, path))

        # Find duplicates
        for (title, href), tags_with_paths in bookmarks.items():
            if len(tags_with_paths) > 1:
                self.duplicate_bookmarks.append((title, href, tags_with_paths))

        self.is_running = False

        if self.duplicate_bookmarks:
            self.log(f"Found {len(self.duplicate_bookmarks)} duplicate bookmarks.")
            for title, href, tags_with_paths in self.duplicate_bookmarks:
                paths_info = "\n".join([f"- Location: {path}" for _, path in tags_with_paths])
                if messagebox.askyesno("Duplicate Bookmarks", 
                    f"Bookmark '{title}' ({href}) has {len(tags_with_paths)} duplicates:\n{paths_info}\n\nDelete duplicates?"):
                    # Keep first one, delete others
                    for tag, _ in tags_with_paths[1:]:
                        tag.decompose()
            self.log("Duplicate processing completed!")
        else:
            self.log("No duplicate bookmarks found.")

    def remove_old_bookmarks(self):
        """Remove bookmarks older than 6 months"""
        if not self.soup:
            self.log("Please load a bookmarks file first!")
            return

        cutoff_date = datetime.now() - timedelta(days=180)
        old_bookmarks = []

        # Collect all old bookmarks and their paths
        for a_tag in self.soup.find_all("a"):
            add_date = a_tag.get("add_date")
            if add_date and datetime.fromtimestamp(int(add_date)) < cutoff_date:
                path = self.get_bookmark_path(a_tag)
                old_bookmarks.append((a_tag, path))

        if old_bookmarks:
            message = f"Found {len(old_bookmarks)} bookmarks older than 6 months:\n\n"
            for _, path in old_bookmarks[:10]:
                message += f"- Location: {path}\n"
            if len(old_bookmarks) > 10:
                message += f"\n... and {len(old_bookmarks) - 10} more\n"
            message += "\nDelete these bookmarks?"
            
            if messagebox.askyesno("Old Bookmarks", message):
                for a_tag, _ in old_bookmarks:
                    a_tag.decompose()
                self.log(f"Successfully removed {len(old_bookmarks)} old bookmarks!")
        else:
            self.log("No bookmarks older than 6 months found.")

    def save_bookmarks(self):
        """Save bookmarks file (maintaining folder structure)"""
        if not self.soup:
            self.log("Please load a bookmarks file first!")
            return
        
        # Check folder structure integrity
        folders = self.soup.find_all("h3")
        dls = self.soup.find_all("dl")
        
        if not folders or not dls:
            self.log("Warning: Bookmark folder structure might be corrupted!")
            if not messagebox.askyesno("Warning", "Bookmark folder structure might be corrupted. Save anyway?"):
                return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML files", "*.html")],
            initialfile="bookmarks.html"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as file:
                    file.write(str(self.soup))
                self.log(f"Bookmarks file saved to: {file_path}")
                
                # Show folder structure statistics
                folder_count = len(folders)
                bookmark_count = len(self.soup.find_all("a"))
                self.log(f"Contains {folder_count} folders, {bookmark_count} bookmarks.")
            except Exception as e:
                self.log(f"Error saving file: {e}")

    def process_bookmarks(self, action):
        """Process bookmarks based on selected action"""
        if action == "remove_old":
            self.remove_old_bookmarks()
        elif action == "check_validity":
            self.check_bookmark_validity()
        elif action == "find_duplicates":
            self.find_duplicate_bookmarks()
        elif action == "save":
            self.save_bookmarks()
        else:
            self.log("Unknown action!")


if __name__ == "__main__":
    root = tk.Tk()
    app = BookmarkManager(root)
    root.mainloop()
