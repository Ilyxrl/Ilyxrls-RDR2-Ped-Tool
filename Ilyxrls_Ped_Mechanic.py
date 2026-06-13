"""
ilyxrl's Ped Mechanic
RDR2 standalone modding tool — Skeleton Merger + YMT Asset Swapper
"""

import xml.etree.ElementTree as ET
import customtkinter as ctk
from tkinter import filedialog, messagebox, Menu
import os
import threading
import re
import platform
import shutil
import subprocess
import json
from datetime import datetime

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

ACCENT        = "#8a0000"
ACCENT_HOVER  = "#6a0000"
ACCENT_DIM    = "#3a0000"
BG_DEEP       = "#0e0e0e"
BG_CARD       = "#181818"
BG_FIELD      = "#111111"
BG_STRIP      = "#141414"
TEXT_DIM      = "#555555"
TEXT_MID      = "#888888"
TEXT_ON       = "#E8E0D0"
BORDER        = "#252525"
BORDER_ACTIVE = "#444444"
SUCCESS       = "#4CAF50"
WARN          = "#e0a020"
ERROR         = "#FF4444"

INSTRUCTIONS_TEXT = """\
SKELETON MERGER
  Load two .yft.xml files (extracted with CodeX).
  File 1 is the "donor" skeleton — missing bones will be copied FROM here.
  File 2 is the "base" skeleton — it receives the new bones.
  Click RUN SKELETON MERGE. Output is saved to the auto-generated Output/ folder.

YMT ASSET SWAPPER
  Load a Donor .ymt and a Receiver .ymt.
  Pick a source outfit slot from the Donor, then tick the clothes you want to move.
  Check which slots in the Receiver should get the new clothes.
  Optionally pick items to wipe from those receiver slots first.
  Click RUN CLOTHING SWAP to write the patched file.

TIPS
  • Drag & drop .xml / .ymt files directly onto the entry fields.
  • Right-click any entry field to copy or clear the path.
  • Use the filter boxes to search within large outfit lists.
  • Recent files are remembered under File → Recent.
"""

CREDITS_TEXT = """\
Backend logic and code written by ilyxrl.
GUI originally designed by Iván Berni.
v4.0 — improved GUI, QoL, and parsing robustness.
"""

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "Output")
RECENT_FILE = os.path.join(SCRIPT_DIR, ".ped_mechanic_recent.json")
MAX_RECENT = 10

def load_recent() -> list[str]:
    try:
        with open(RECENT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [p for p in data if os.path.isfile(p)]
    except Exception:
        return []

def push_recent(path: str):
    recent = load_recent()
    path = os.path.normpath(path)
    if path in recent:
        recent.remove(path)
    recent.insert(0, path)
    recent = recent[:MAX_RECENT]
    try:
        with open(RECENT_FILE, "w", encoding="utf-8") as f:
            json.dump(recent, f, indent=2)
    except Exception:
        pass

def count_bones(path: str) -> int | None:
    try:
        tree = ET.parse(path)
        bones = tree.getroot().find(".//Skeleton/Bones")
        if bones is None:
            return None
        return len(bones.findall("Item"))
    except Exception:
        return None

def validate_xml_structure(root, label: str):
    bones_parent = root.find(".//Skeleton/Bones")
    if bones_parent is None:
        raise ValueError(f"{label}: Could not find Bones section")
    transforms = root.find(".//BoneTransforms")
    if transforms is None:
        raise ValueError(f"{label}: Could not find BoneTransforms section")
    return bones_parent, transforms

def merge_clothing_bones(
    mp_path: str,
    mb_path: str,
    output_path: str,
    progress_callback=None,
    log_fn=print,
) -> tuple[int, int]:
    log_fn("Starting skeleton merge...")
    ET.register_namespace("", "")

    mp_tree = ET.parse(mp_path)
    mb_tree = ET.parse(mb_path)
    mp_root, mb_root = mp_tree.getroot(), mb_tree.getroot()

    mp_bones, _ = validate_xml_structure(mp_root, "Donor")
    mb_bones, mb_transforms = validate_xml_structure(mb_root, "Base Skeleton")

    mb_bone_names: list[str] = []
    mb_bone_map: dict[str, int] = {}
    max_mb_idx = -1

    for item in mb_bones.findall("Item"):
        name_node = item.find("Name")
        idx_node = item.find("Index")
        if name_node is not None and name_node.text:
            bname = name_node.text.strip()
            mb_bone_names.append(bname)
            if idx_node is not None and idx_node.get("value"):
                try:
                    bidx = int(idx_node.get("value"))
                    mb_bone_map[bname] = bidx
                    if bidx > max_mb_idx:
                        max_mb_idx = bidx
                except ValueError:
                    pass

    mb_original_count = len(mb_bone_names)
    log_fn(f"Base skeleton has {mb_original_count} bones.")

    mp_idx_to_name: dict[int, str] = {}
    for bone in mp_bones.findall("Item"):
        name_node = bone.find("Name")
        idx_node = bone.find("Index")
        if name_node is not None and name_node.text and idx_node is not None:
            try:
                mp_idx_to_name[int(idx_node.get("value"))] = name_node.text.strip()
            except (TypeError, ValueError):
                pass

    missing_mp_bones = []
    for item in mp_bones.findall("Item"):
        name_node = item.find("Name")
        if name_node is not None and name_node.text:
            if name_node.text.strip() not in mb_bone_map:
                missing_mp_bones.append(item)

    log_fn(f"Found {len(missing_mp_bones)} missing bones to copy from donor.")

    if not missing_mp_bones:
        mb_tree.write(output_path, encoding="UTF-8", xml_declaration=True)
        return 0, mb_original_count

    added_count = 0
    current_new_idx = max_mb_idx + 1
    total_to_add = len(missing_mp_bones)

    for i, mp_bone in enumerate(missing_mp_bones):
        orig_name = mp_bone.find("Name").text.strip()

        parent_node = mp_bone.find("ParentIndex")
        orig_parent_idx = int(parent_node.get("value")) if parent_node is not None else 0
        parent_name = mp_idx_to_name.get(orig_parent_idx, "SKEL_ROOT")
        new_parent_idx = mb_bone_map.get(parent_name, 0)

        new_bone = ET.fromstring(ET.tostring(mp_bone))
        new_bone.find("Index").set("value", str(current_new_idx))
        new_bone.find("ParentIndex").set("value", str(new_parent_idx))

        sib_next = new_bone.find("NextSiblingIndex")
        if sib_next is not None:
            sib_next.set("value", "-1")
        sib_last = new_bone.find("LastSiblingIndex")
        if sib_last is not None:
            sib_last.set("value", str(current_new_idx))

        mb_bones.append(new_bone)

        new_transform = ET.Element("Item")
        for tag in ("Heading", "Pitch", "Roll", "X", "Y", "Z"):
            ET.SubElement(new_transform, tag).set("value", "0.00000000")
        mb_transforms.append(new_transform)

        mb_bone_map[orig_name] = current_new_idx
        current_new_idx += 1
        added_count += 1

        if progress_callback:
            progress_callback((i + 1) / total_to_add)

    final_bone_count = current_new_idx
    log_fn(f"New total bone count: {final_bone_count}.")

    mb_root_bone = mb_bones.find("./Item[Name='SKEL_ROOT']")
    if mb_root_bone is not None:
        last_sib = mb_root_bone.find("LastSiblingIndex")
        if last_sib is not None:
            last_sib.set("value", str(final_bone_count - 1))

    mb_tree.write(output_path, encoding="UTF-8", xml_declaration=True)
    log_fn("File saved successfully.")
    return added_count, final_bone_count


def get_safe_output_path(base_path: str) -> str:
    if not os.path.exists(base_path):
        return base_path
    root, ext = os.path.splitext(base_path)
    if root.endswith(".yft"):
        root = root[:-4]
        ext = ".yft" + ext
    counter = 2
    while True:
        candidate = f"{root}_{counter}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def open_in_editor(path: str):
    if not path or not os.path.isfile(path):
        messagebox.showwarning("No file", "Please select a valid file to open.")
        return
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-t", path])
        else:
            for ed in ("xdg-open", "gedit", "nano", "vi"):
                if shutil.which(ed):
                    subprocess.Popen([ed, path])
                    return
    except Exception as e:
        messagebox.showerror("Error", str(e))


def reveal_in_explorer(path: str):
    """Open the file's parent folder and select the file where supported."""
    if not path:
        return
    folder = os.path.dirname(path) if os.path.isfile(path) else path
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception as e:
        messagebox.showerror("Error", str(e))


def get_text_file_content(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def scan_ymt_outfit_names_text(path: str) -> list[str]:
    text = get_text_file_content(path)
    return [n.strip() for n in re.findall(r"<name>(.*?)</name>", text, re.IGNORECASE) if n.strip()]

def get_outfit_block_bounds(text: str, slot_idx: int) -> tuple[int, int] | None:
    matches = list(re.finditer(r"<name>(.*?)</name>", text, re.IGNORECASE))
    if not matches or slot_idx >= len(matches):
        return None
    start_pos = max(0, text.rfind("<Item>", 0, matches[slot_idx].start()))
    if slot_idx + 1 < len(matches):
        end_pos = max(start_pos, text.rfind("<Item>", 0, matches[slot_idx + 1].start()))
    else:
        end_pos = text.find("</outfits>", start_pos)
        if end_pos == -1:
            end_pos = len(text)
    return (start_pos, end_pos)

def scan_drawables_in_slot_text(path: str, slot_idx: int) -> list[str]:
    text = get_text_file_content(path)
    bounds = get_outfit_block_bounds(text, slot_idx)
    if not bounds:
        return []
    chunk = text[bounds[0]:bounds[1]]
    names: list[str] = []
    for d in re.findall(r"<drawable>(.*?)</drawable>", chunk, re.IGNORECASE):
        d = d.strip()
        if d and d not in names:
            names.append(d)
    return names

def parse_items_from_assets_chunk(assets_chunk: str) -> list[str]:
    items, pos = [], 0
    while True:
        start = assets_chunk.find("<Item>", pos)
        if start == -1:
            break
        end = assets_chunk.find("</Item>", start)
        if end == -1:
            break
        items.append(assets_chunk[start : end + 7])
        pos = end + 7
    return items

def run_text_ymt_injection(
    donor_path: str,
    recip_path: str,
    out_path: str,
    src_slot: int,
    target_slots: list[int],
    selected_drawables: list[str],
    wipe_drawables: list[str],
    do_full_swap: bool,
    log_callback=None,
):
    def log(msg, cat="info"):
        if log_callback:
            log_callback(msg, cat)

    d_text = get_text_file_content(donor_path)
    r_text = get_text_file_content(recip_path)

    d_bounds = get_outfit_block_bounds(d_text, src_slot)
    if not d_bounds:
        raise ValueError(f"Could not locate outfit slot {src_slot} in donor file.")

    d_outfit_chunk = d_text[d_bounds[0] : d_bounds[1]]

    da_start = d_outfit_chunk.find("<explicitAssets>")
    da_end = d_outfit_chunk.find("</explicitAssets>") + 17
    if da_start == -1 or da_end < 17:
        raise ValueError("Could not find <explicitAssets> block in donor slot.")
    donor_assets_full_block = d_outfit_chunk[da_start:da_end]

    de_start = d_outfit_chunk.find("<expressions")
    if de_start == -1:
        donor_expressions_block = ""
    elif d_outfit_chunk[de_start : de_start + 14] == "<expressions/>":
        donor_expressions_block = "<expressions/>"
    else:
        de_end = d_outfit_chunk.find("</expressions>", de_start) + 14
        donor_expressions_block = d_outfit_chunk[de_start:de_end]

    for t_idx in sorted(target_slots, reverse=True):
        r_bounds = get_outfit_block_bounds(r_text, t_idx)
        if not r_bounds:
            log(f"Slot {t_idx} not found in receiver — skipping.", "warn")
            continue

        r_outfit_chunk = r_text[r_bounds[0] : r_bounds[1]]

        ra_start = r_outfit_chunk.find("<explicitAssets>")
        ra_end = r_outfit_chunk.find("</explicitAssets>") + 17
        if ra_start == -1 or ra_end < 17:
            log(f"No <explicitAssets> in receiver slot {t_idx} — skipping.", "warn")
            continue

        re_start = r_outfit_chunk.find("<expressions")
        if re_start != -1:
            if r_outfit_chunk[re_start : re_start + 14] == "<expressions/>":
                re_end = re_start + 14
            else:
                re_end = r_outfit_chunk.find("</expressions>", re_start) + 14
        else:
            re_end = ra_end

        if do_full_swap:
            log(f"Full-replacing slot {t_idx} with donor data...", "warn")
            expr_part = (donor_expressions_block + "\n") if donor_expressions_block else ""
            new_outfit_chunk = (
                r_outfit_chunk[:ra_start]
                + donor_assets_full_block
                + "\n"
                + expr_part
                + r_outfit_chunk[re_end:]
            )
        else:
            r_assets_block = r_outfit_chunk[ra_start:ra_end]
            recipient_items = parse_items_from_assets_chunk(r_assets_block)
            donor_items = parse_items_from_assets_chunk(donor_assets_full_block)

            items_to_keep = []
            for item in recipient_items:
                m = re.search(r"<drawable>(.*?)</drawable>", item, re.IGNORECASE)
                rname = m.group(1).strip() if m else ""
                if rname in wipe_drawables:
                    log(f"Removed: {rname} from slot {t_idx}", "warn")
                else:
                    items_to_keep.append(item)

            for d_item in donor_items:
                m = re.search(r"<drawable>(.*?)</drawable>", d_item, re.IGNORECASE)
                dname = m.group(1).strip() if m else ""
                if dname in selected_drawables:

                    items_to_keep = [
                        it for it in items_to_keep
                        if f"<drawable>{dname}</drawable>" not in it
                    ]
                    items_to_keep.append(d_item)
                    log(f"Added: {dname}", "success")

            built_assets = (
                "<explicitAssets>\n"
                + "\n".join(items_to_keep)
                + "\n</explicitAssets>"
            )
            new_outfit_chunk = (
                r_outfit_chunk[:ra_start] + built_assets + r_outfit_chunk[ra_end:]
            )

        r_text = r_text[: r_bounds[0]] + new_outfit_chunk + r_text[r_bounds[1] :]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(r_text)


def make_label(parent, text, size=10, weight="bold", color=TEXT_DIM, anchor="w", **kw):
    return ctk.CTkLabel(
        parent,
        text=text,
        font=ctk.CTkFont(family="Courier New", size=size, weight=weight),
        text_color=color,
        anchor=anchor,
        **kw,
    )

def make_button(parent, text, command, width=None, accent=False, small=False, **kw):
    size = 11 if small else 13
    h = 30 if small else 38
    fg = ACCENT if accent else BG_CARD
    hover = ACCENT_HOVER if accent else "#222222"
    border = ACCENT if accent else BORDER
    btn_kw = dict(
        text=text,
        font=ctk.CTkFont(family="Courier New", size=size, weight="bold"),
        fg_color=fg,
        hover_color=hover,
        border_color=border,
        border_width=1,
        text_color="#FFFFFF",
        height=h,
        corner_radius=3,
        command=command,
    )
    if width:
        btn_kw["width"] = width
    btn_kw.update(kw)
    return ctk.CTkButton(parent, **btn_kw)


class PathEntry(ctk.CTkEntry):
    """Entry widget with right-click context menu (copy / clear / reveal) and basic drag-drop."""

    def __init__(self, parent, var: ctk.StringVar, **kw):
        super().__init__(
            parent,
            textvariable=var,
            font=ctk.CTkFont(family="Courier New", size=12),
            fg_color=BG_FIELD,
            border_color=BORDER,
            border_width=1,
            text_color=TEXT_ON,
            placeholder_text_color=TEXT_DIM,
            height=36,
            corner_radius=3,
            **kw,
        )
        self._var = var
        self.bind("<Button-3>", self._right_click)
        self.bind("<Button-2>", self._right_click)  # macOS

        try:
            self.drop_target_register("DND_Files")  # type: ignore[attr-defined]
            self.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _on_drop(self, event):
        path = event.data.strip().strip("{}")
        if os.path.isfile(path):
            self._var.set(path)

    def _right_click(self, event):
        menu = Menu(
            self,
            tearoff=0,
            bg=BG_CARD,
            fg=TEXT_ON,
            activebackground=ACCENT,
            activeforeground="#111111",
            font=("Courier New", 11),
            bd=0,
            relief="flat",
        )
        menu.add_command(label="Copy path", command=lambda: self._copy())
        menu.add_command(label="Clear", command=lambda: self._var.set(""))
        menu.add_separator()
        menu.add_command(
            label="Reveal in Explorer", command=lambda: reveal_in_explorer(self._var.get())
        )
        menu.tk_popup(event.x_root, event.y_root)

    def _copy(self):
        val = self._var.get()
        if val:
            self.clipboard_clear()
            self.clipboard_append(val)


class LogBox(ctk.CTkTextbox):
    TAG_COLORS = {
        "success": SUCCESS,
        "error": ERROR,
        "warn": WARN,
        "info": "#7CFC7C",
    }

    def __init__(self, parent, **kw):
        super().__init__(
            parent,
            font=ctk.CTkFont(family="Courier New", size=11),
            fg_color=BG_FIELD,
            text_color="#7CFC7C",
            border_color=BORDER,
            border_width=1,
            corner_radius=3,
            wrap="word",
            state="disabled",
            **kw,
        )
        for tag, color in self.TAG_COLORS.items():
            self.tag_config(tag, foreground=color)

    def log(self, msg: str, category: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.configure(state="normal")
        self.insert("end", f"[{ts}] ", "ts")
        self.tag_config("ts", foreground=TEXT_DIM)
        self.insert("end", f"[{category.upper():7s}] ", category)
        self.insert("end", f"{msg}\n")
        self.see("end")
        self.configure(state="disabled")

    def clear(self):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")

    def copy_all(self):
        self.clipboard_clear()
        self.clipboard_append(self.get("1.0", "end"))


class PedMechanicApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ilyxrl's Ped Mechanic  v4.0")
        self.geometry("1180x820")
        self.minsize(900, 680)
        self.configure(fg_color=BG_DEEP)

        self.file1_path = ctk.StringVar()
        self.file2_path = ctk.StringVar()
        self._output_resolved = ""

        self.donor_path_var = ctk.StringVar()
        self.recip_path_var = ctk.StringVar()
        self.src_slot_var = ctk.IntVar(value=-1)
        self.drawable_checkboxes: list[tuple[str, ctk.CTkCheckBox, ctk.BooleanVar]] = []
        self.wipe_checkboxes: list[tuple[str, ctk.CTkCheckBox, ctk.BooleanVar]] = []
        self.target_vars: list[tuple[int, ctk.BooleanVar]] = []
        self.full_swap_var = ctk.BooleanVar(value=False)
        self.master_drawables: list[str] = []
        self.master_wipes: list[str] = []

        self._bones1_label: ctk.CTkLabel | None = None
        self._bones2_label: ctk.CTkLabel | None = None
        self._bones_out_label: ctk.CTkLabel | None = None

        self._build_ui()

        self.file1_path.trace_add("write", lambda *_: self._refresh_bone_count(self.file1_path, self._bones1_label))
        self.file2_path.trace_add("write", lambda *_: self._refresh_bone_count(self.file2_path, self._bones2_label))

    def _build_ui(self):
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.pack(fill="x", padx=28, pady=(20, 6))

        title_left = ctk.CTkFrame(title_frame, fg_color="transparent")
        title_left.pack(side="left", fill="y")

        make_label(title_left, "ILYXRL'S", size=11, color=ACCENT).pack(side="left", anchor="s", pady=(0, 5))
        make_label(title_left, " PED MECHANIC", size=26, color=TEXT_ON).pack(side="left")

        make_label(title_frame, "RDR2 MOD TOOLKIT", size=10, color=TEXT_DIM).pack(side="left", padx=(12, 0), anchor="s", pady=(0, 6))

        btn_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        btn_frame.pack(side="right", anchor="center")

        self._about_btn = make_button(btn_frame, "ABOUT ▾", self._show_about_menu, width=88, small=True)
        self._about_btn.pack(side="left", padx=(4, 0))

        ctk.CTkFrame(self, height=1, fg_color=BORDER).pack(fill="x", padx=28, pady=(0, 8))

        self.tabs = ctk.CTkTabview(
            self,
            fg_color=BG_DEEP,
            segmented_button_fg_color=BG_CARD,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_HOVER,
            segmented_button_unselected_color=BG_CARD,
            segmented_button_unselected_hover_color="#222222",
            text_color=TEXT_ON,
        )
        self.tabs._segmented_button.configure(
            font=ctk.CTkFont(family="Courier New", size=12, weight="bold")
        )
        self.tabs.pack(fill="both", expand=True, padx=28, pady=0)

        tab_merge = self.tabs.add("  Skeleton Merger  ")
        tab_ymt   = self.tabs.add("  YMT Asset Swapper  ")

        self._build_skeleton_merge_tab(tab_merge)
        self._build_ymt_swapper_tab(tab_ymt)

        log_header = ctk.CTkFrame(self, fg_color="transparent")
        log_header.pack(fill="x", padx=28, pady=(6, 2))
        make_label(log_header, "LOG", size=10, color=TEXT_DIM).pack(side="left")
        make_button(log_header, "COPY", self._copy_log, width=60, small=True).pack(side="right")
        make_button(log_header, "CLEAR", self._clear_log, width=60, small=True).pack(side="right", padx=(0, 4))

        self.log_box = LogBox(self, height=120)
        self.log_box.pack(fill="x", padx=28, pady=(0, 18))
        self._log("Ped Mechanic v4.0 ready.", "success")

    def _build_skeleton_merge_tab(self, master):
        inner = ctk.CTkFrame(master, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=10, pady=10)

        make_label(inner, "RED DEAD REDEMPTION 2  —  SKELETON MERGER", size=12, color=TEXT_MID).pack(anchor="w", pady=(0, 14))

        self._bones1_label = self._file_row(inner, "BASE .YFT.XML", self.file1_path, self._pick_skeleton_f1)
        self._divider_symbol(inner, "+")
        self._bones2_label = self._file_row(inner, "BASE  YFT.XML", self.file2_path, self._pick_skeleton_f2)
        self._divider_symbol(inner, "=")
        self._bones_out_label = self._output_row(inner)

        self.progress = ctk.CTkProgressBar(inner, height=6, fg_color=BG_FIELD, progress_color=ACCENT, corner_radius=2)
        self.progress.pack(fill="x", pady=(18, 8))
        self.progress.set(0)

        self.merge_btn = make_button(inner, "RUN SKELETON MERGE", self._start_merge_thread, accent=True)
        self.merge_btn.configure(height=44, font=ctk.CTkFont(family="Courier New", size=14, weight="bold"))
        self.merge_btn.pack(fill="x", pady=(6, 0))

    def _divider_symbol(self, parent, char: str):
        ctk.CTkLabel(
            parent,
            text=char,
            font=ctk.CTkFont(family="Courier New", size=22, weight="bold"),
            text_color=ACCENT,
        ).pack(pady=2)

    def _file_row(self, master, label_text: str, var: ctk.StringVar, pick_cmd) -> ctk.CTkLabel:
        outer = ctk.CTkFrame(master, fg_color=BG_CARD, corner_radius=4)
        outer.pack(fill="x", pady=4)

        top = ctk.CTkFrame(outer, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(8, 4))

        make_label(top, label_text, size=10, color=TEXT_DIM).pack(side="left")
        bone_lbl = ctk.CTkLabel(
            top,
            text="",
            font=ctk.CTkFont(family="Courier New", size=11, weight="bold"),
            text_color=SUCCESS,
        )
        bone_lbl.pack(side="left", padx=(10, 0))

        row = ctk.CTkFrame(outer, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 10))

        entry = PathEntry(row, var, placeholder_text="no file selected")
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        make_button(row, "BROWSE", pick_cmd, width=80, small=True).pack(side="left", padx=(0, 4))
        make_button(row, "EDIT", lambda: open_in_editor(var.get()), width=52, small=True).pack(side="left")
        return bone_lbl

    def _output_row(self, master) -> ctk.CTkLabel:
        outer = ctk.CTkFrame(master, fg_color=BG_CARD, corner_radius=4)
        outer.pack(fill="x", pady=4)

        top = ctk.CTkFrame(outer, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(8, 4))

        make_label(top, "OUTPUT FILE", size=10, color=TEXT_DIM).pack(side="left")
        out_bone_lbl = ctk.CTkLabel(
            top,
            text="",
            font=ctk.CTkFont(family="Courier New", size=11, weight="bold"),
            text_color=SUCCESS,
        )
        out_bone_lbl.pack(side="left", padx=(10, 0))

        row = ctk.CTkFrame(outer, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 10))

        self._out_var = ctk.StringVar(value="")
        self.out_entry = ctk.CTkEntry(
            row,
            textvariable=self._out_var,
            placeholder_text="— run merge to generate —",
            font=ctk.CTkFont(family="Courier New", size=12),
            fg_color=BG_FIELD,
            border_color=BORDER,
            border_width=1,
            text_color=TEXT_MID,
            placeholder_text_color=TEXT_DIM,
            height=36,
            corner_radius=3,
            state="disabled",
        )
        self.out_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        make_button(row, "SAVE AS", self._save_as_output, width=80, small=True).pack(side="left", padx=(0, 4))
        make_button(row, "REVEAL", lambda: reveal_in_explorer(self._output_resolved), width=68, small=True).pack(side="left", padx=(0, 4))
        make_button(row, "EDIT", lambda: open_in_editor(self._output_resolved), width=52, small=True).pack(side="left")
        return out_bone_lbl

    def _refresh_bone_count(self, var: ctk.StringVar, label: ctk.CTkLabel | None):
        if label is None:
            return
        path = var.get().strip()
        if not path or not os.path.isfile(path):
            label.configure(text="")
            return
        label.configure(text="counting...", text_color=TEXT_MID)
        def worker():
            n = count_bones(path)
            if n is not None:
                self.after(0, lambda: label.configure(text=f"· {n} bones", text_color=SUCCESS))
            else:
                self.after(0, lambda: label.configure(text="· unreadable", text_color=ERROR))
        threading.Thread(target=worker, daemon=True).start()

    def _pick_skeleton_f1(self):
        path = filedialog.askopenfilename(filetypes=[("XML files", "*.xml"), ("All files", "*.*")])
        if path:
            self.file1_path.set(path)
            push_recent(path)

    def _pick_skeleton_f2(self):
        path = filedialog.askopenfilename(filetypes=[("XML files", "*.xml"), ("All files", "*.*")])
        if path:
            self.file2_path.set(path)
            push_recent(path)

    def _build_output_path(self) -> str:
        f1 = self.file1_path.get().strip()
        if not f1:
            return ""
        basename = os.path.basename(f1)
        root, ext = os.path.splitext(basename)
        if root.endswith(".yft"):
            root = root[:-4]
            ext = ".yft.xml"
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        return os.path.join(OUTPUT_DIR, root + "_merged" + ext)

    def _save_as_output(self):
        if not self._output_resolved or not os.path.isfile(self._output_resolved):
            messagebox.showwarning("No output", "Run the merge first.")
            return
        dest = filedialog.asksaveasfilename(
            initialfile=os.path.basename(self._output_resolved),
            defaultextension=".xml",
            filetypes=[("XML files", "*.xml")],
        )
        if dest:
            shutil.copy2(self._output_resolved, dest)
            self._log(f"Saved to: {dest}", "success")

    def _start_merge_thread(self):
        f1, f2 = self.file1_path.get().strip(), self.file2_path.get().strip()
        if not f1 or not os.path.isfile(f1) or not f2 or not os.path.isfile(f2):
            messagebox.showerror("Missing files", "Select both YFT.XML files before merging.")
            return

        intended = self._build_output_path()
        if not intended:
            return
        out = get_safe_output_path(intended)
        if out != intended:
            self._log(f"Output already exists — saving as: {os.path.basename(out)}", "warn")

        self.merge_btn.configure(state="disabled", text="MERGING SKELETONS...")
        self.progress.set(0)

        def worker():
            try:
                added, total = merge_clothing_bones(
                    f1, f2, out,
                    progress_callback=lambda v: self.after(0, lambda: self.progress.set(v)),
                    log_fn=lambda m: self.after(0, lambda: self._log(m, "info")),
                )
                self.after(0, lambda: self._on_merge_complete(out, added, total))
            except Exception as e:
                self.after(0, lambda: self._log(f"Error: {e}", "error"))
                self.after(0, lambda: self.merge_btn.configure(state="normal", text="RUN SKELETON MERGE"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_merge_complete(self, out_path: str, added: int, total: int):
        self.merge_btn.configure(state="normal", text="RUN SKELETON MERGE")
        self._output_resolved = out_path
        self._out_var.set(os.path.basename(out_path))
        self.progress.set(1)
        self._log(f"Done! Added {added} bones. Total: {total}. Saved: {os.path.basename(out_path)}", "success")
        self._bones_out_label.configure(text=f"· {total} bones", text_color=SUCCESS)
        messagebox.showinfo("Merge complete", f"Added {added} missing bones.\nTotal skeleton size: {total} bones.")

    def _build_ymt_swapper_tab(self, master):

        file_card = ctk.CTkFrame(master, fg_color=BG_CARD, corner_radius=4)
        file_card.pack(fill="x", padx=10, pady=(10, 6))
        file_card.columnconfigure(1, weight=1)

        def ymt_row(row_idx, label, var, browse_cmd):
            make_label(file_card, label, size=10, color=TEXT_DIM).grid(
                row=row_idx, column=0, padx=(12, 8), pady=7, sticky="e"
            )
            entry = PathEntry(file_card, var, placeholder_text="no file selected")
            entry.grid(row=row_idx, column=1, padx=(0, 8), pady=7, sticky="ew")
            make_button(file_card, "BROWSE", browse_cmd, width=72, small=True).grid(
                row=row_idx, column=2, padx=(0, 12), pady=7
            )

        ymt_row(0, "DONOR  (source)  YMT:", self.donor_path_var, self._browse_donor_ymt)
        ymt_row(1, "RECEIVER  (target)  YMT:", self.recip_path_var, self._browse_recip_ymt)

        self.grid_frame = ctk.CTkFrame(master, fg_color="transparent")
        self.grid_frame.pack(fill="both", expand=True, padx=10, pady=4)
        for col, w in enumerate((2, 3, 2, 3)):
            self.grid_frame.columnconfigure(col, weight=w)
        self.grid_frame.rowconfigure(0, weight=1)

        def scrollable(parent, col, label):
            f = ctk.CTkScrollableFrame(
                parent,
                label_text=label,
                label_font=ctk.CTkFont(family="Courier New", size=10, weight="bold"),
                label_text_color=TEXT_MID,
                fg_color=BG_FIELD,
                border_color=BORDER,
                border_width=1,
                corner_radius=3,
            )
            f.grid(row=0, column=col, padx=4, pady=4, sticky="nsew")
            return f

        def scrollable_with_search(parent, col, frame_label, search_placeholder, on_key):
            container = ctk.CTkFrame(parent, fg_color="transparent")
            container.grid(row=0, column=col, padx=4, pady=4, sticky="nsew")
            container.rowconfigure(1, weight=1)
            container.columnconfigure(0, weight=1)

            search = ctk.CTkEntry(
                container,
                placeholder_text=search_placeholder,
                font=ctk.CTkFont(family="Courier New", size=11),
                fg_color=BG_FIELD,
                border_color=BORDER,
                border_width=1,
                height=28,
                corner_radius=3,
            )
            search.grid(row=0, column=0, sticky="ew", pady=(0, 4))
            search.bind("<KeyRelease>", on_key)

            box = ctk.CTkScrollableFrame(
                container,
                label_text=frame_label,
                label_font=ctk.CTkFont(family="Courier New", size=10, weight="bold"),
                label_text_color=TEXT_MID,
                fg_color=BG_FIELD,
                border_color=BORDER,
                border_width=1,
                corner_radius=3,
            )
            box.grid(row=1, column=0, sticky="nsew")
            return search, box

        self.donor_box = scrollable(self.grid_frame, 0, "1. SOURCE OUTFIT SLOT")
        self.donor_search, self.drawables_box = scrollable_with_search(
            self.grid_frame, 1, "2. SELECT CLOTHES TO COPY", "Filter...", lambda e: self.filter_donor_display()
        )
        self.recip_box = scrollable(self.grid_frame, 2, "3. TARGET OUTFIT SLOTS")
        self.recip_search, self.wipe_box = scrollable_with_search(
            self.grid_frame, 3, "4. CLOTHES TO REMOVE FROM RECEIVER", "Filter...", lambda e: self.filter_recip_wipe_display()
        )

        action_row = ctk.CTkFrame(master, fg_color="transparent")
        action_row.pack(fill="x", padx=10, pady=(4, 10))
        action_row.columnconfigure(0, weight=1)

        self.swap_btn = make_button(action_row, "RUN CLOTHING SWAP", self._execute_ymt_swap, accent=True)
        self.swap_btn.configure(height=44, font=ctk.CTkFont(family="Courier New", size=14, weight="bold"))
        self.swap_btn.grid(row=0, column=0, sticky="ew")

    def _browse_donor_ymt(self):
        path = filedialog.askopenfilename(filetypes=[("YMT Files", "*.ymt"), ("All files", "*.*")])
        if path:
            self.donor_path_var.set(path)
            push_recent(path)
            self._update_donor_slots(path)

    def _browse_recip_ymt(self):
        path = filedialog.askopenfilename(filetypes=[("YMT Files", "*.ymt"), ("All files", "*.*")])
        if path:
            self.recip_path_var.set(path)
            push_recent(path)
            self._update_recip_slots(path)

    def _update_donor_slots(self, path: str):
        for w in self.donor_box.winfo_children():
            w.destroy()
        self.src_slot_var.set(-1)
        slots = scan_ymt_outfit_names_text(path)
        self._log(f"Donor loaded. {len(slots)} outfit slots found.", "info")
        for idx, name in enumerate(slots):
            ctk.CTkRadioButton(
                self.donor_box,
                text=f"[{idx:02d}]  {name}",
                value=idx,
                variable=self.src_slot_var,
                font=ctk.CTkFont(family="Courier New", size=11),
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                text_color=TEXT_ON,
                command=self.on_donor_slot_selected,
            ).pack(anchor="w", padx=8, pady=3)
        self._clear_drawables_box()

    def on_donor_slot_selected(self):
        path = self.donor_path_var.get().strip()
        slot = self.src_slot_var.get()
        if not path or slot == -1:
            return
        self.master_drawables = scan_drawables_in_slot_text(path, slot)
        self._log(f"Donor slot {slot}: {len(self.master_drawables)} items found.", "info")
        self.filter_donor_display()

    def filter_donor_display(self):
        for w in self.drawables_box.winfo_children():
            w.destroy()
        self.drawable_checkboxes.clear()

        query = self.donor_search.get().strip().lower()

        cb_all = ctk.CTkCheckBox(
            self.drawables_box,
            text="SELECT ALL  /  REPLACE ENTIRE OUTFIT",
            variable=self.full_swap_var,
            font=ctk.CTkFont(family="Courier New", size=11, weight="bold"),
            text_color=WARN,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        cb_all.pack(anchor="w", padx=8, pady=(6, 8))

        ctk.CTkFrame(self.drawables_box, height=1, fg_color=BORDER).pack(fill="x", padx=4, pady=(0, 4))

        shown = 0
        for dname in self.master_drawables:
            if query and query not in dname.lower():
                continue
            var = ctk.BooleanVar()
            cb = ctk.CTkCheckBox(
                self.drawables_box,
                text=dname,
                variable=var,
                font=ctk.CTkFont(family="Courier New", size=11),
                text_color=TEXT_ON,
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
            )
            cb.pack(anchor="w", padx=8, pady=2)
            self.drawable_checkboxes.append((dname, cb, var))
            shown += 1

        if query and not shown:
            make_label(self.drawables_box, "  no results", size=11, color=TEXT_DIM).pack(padx=8, pady=4)

    def _clear_drawables_box(self):
        for w in self.drawables_box.winfo_children():
            w.destroy()
        self.drawable_checkboxes.clear()
        self.master_drawables.clear()
        self.donor_search.delete(0, "end")
        self.full_swap_var.set(False)

    def _update_recip_slots(self, path: str):
        for w in self.recip_box.winfo_children():
            w.destroy()
        self.target_vars.clear()
        slots = scan_ymt_outfit_names_text(path)
        self._log(f"Receiver loaded. {len(slots)} outfit slots found.", "info")
        for idx, name in enumerate(slots):
            var = ctk.BooleanVar()
            cb = ctk.CTkCheckBox(
                self.recip_box,
                text=f"[{idx:02d}]  {name}",
                variable=var,
                font=ctk.CTkFont(family="Courier New", size=11),
                text_color=TEXT_ON,
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                command=self.on_recipient_slot_toggled,
            )
            cb.pack(anchor="w", padx=8, pady=3)
            self.target_vars.append((idx, var))
        self._clear_wipe_box()

    def on_recipient_slot_toggled(self):
        path = self.recip_path_var.get().strip()
        if not path:
            return
        self.master_wipes = []
        for idx, var in self.target_vars:
            if var.get():
                for dname in scan_drawables_in_slot_text(path, idx):
                    if dname not in self.master_wipes:
                        self.master_wipes.append(dname)
        self.filter_recip_wipe_display()

    def filter_recip_wipe_display(self):
        previously_checked = {dname for dname, _, var in self.wipe_checkboxes if var.get()}
        for w in self.wipe_box.winfo_children():
            w.destroy()
        self.wipe_checkboxes.clear()

        query = self.recip_search.get().strip().lower()
        shown = 0

        for dname in self.master_wipes:
            if query and query not in dname.lower():
                continue
            w_var = ctk.BooleanVar(value=(dname in previously_checked))
            cb = ctk.CTkCheckBox(
                self.wipe_box,
                text=dname,
                variable=w_var,
                font=ctk.CTkFont(family="Courier New", size=11),
                text_color=ERROR,
                fg_color=ACCENT_DIM,
                hover_color=ACCENT_HOVER,
                checkmark_color=ERROR,
            )
            cb.pack(anchor="w", padx=8, pady=2)
            self.wipe_checkboxes.append((dname, cb, w_var))
            shown += 1

        if query and not shown:
            make_label(self.wipe_box, "  no results", size=11, color=TEXT_DIM).pack(padx=8, pady=4)

    def _clear_wipe_box(self):
        for w in self.wipe_box.winfo_children():
            w.destroy()
        self.wipe_checkboxes.clear()
        self.master_wipes.clear()
        self.recip_search.delete(0, "end")

    def _execute_ymt_swap(self):
        d_path = self.donor_path_var.get().strip()
        r_path = self.recip_path_var.get().strip()
        src_slot = self.src_slot_var.get()

        if not d_path or not r_path:
            messagebox.showerror("Missing files", "Load both a Donor and Receiver YMT.")
            return
        if src_slot == -1:
            messagebox.showerror("No donor slot", "Select a source outfit slot from the Donor.")
            return

        target_slots = [idx for idx, var in self.target_vars if var.get()]
        if not target_slots:
            messagebox.showerror("No target slots", "Check at least one target slot in the Receiver.")
            return

        do_full_swap = self.full_swap_var.get()
        selected_drawables = [dn for dn, _, var in self.drawable_checkboxes if var.get()]
        wipe_drawables = [dn for dn, _, var in self.wipe_checkboxes if var.get()]

        if not do_full_swap and not selected_drawables and not wipe_drawables:
            messagebox.showerror(
                "Nothing selected",
                "Either check 'Select All', pick clothes to copy, or pick items to remove.",
            )
            return

        out_path = filedialog.asksaveasfilename(
            defaultextension=".ymt",
            filetypes=[("YMT Files", "*.ymt"), ("All files", "*.*")],
            initialdir=OUTPUT_DIR,
        )
        if not out_path:
            return
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        self.swap_btn.configure(state="disabled", text="RUNNING SWAP...")
        try:
            self._log("Starting clothing swap...", "info")
            run_text_ymt_injection(
                d_path, r_path, out_path,
                src_slot, target_slots,
                selected_drawables, wipe_drawables,
                do_full_swap,
                log_callback=self._log,
            )
            push_recent(out_path)
            self._log(f"Saved: {os.path.basename(out_path)}", "success")
            messagebox.showinfo(
                "Swap complete",
                f"Clothing swap finished.\nSaved to:\n{os.path.basename(out_path)}",
            )
        except Exception as e:
            self._log(f"Error: {e}", "error")
            messagebox.showerror("Error", f"Swap failed:\n{e}")
        finally:
            self.swap_btn.configure(state="normal", text="RUN CLOTHING SWAP")

    def _log(self, msg: str, category: str = "info"):
        self.log_box.log(msg, category)

    def _clear_log(self):
        self.log_box.clear()

    def _copy_log(self):
        self.log_box.copy_all()
        self._log("Log copied to clipboard.", "info")

    def _show_about_menu(self):
        menu = Menu(
            self,
            tearoff=0,
            bg=BG_CARD,
            fg=TEXT_ON,
            activebackground=ACCENT,
            activeforeground="#111111",
            font=("Courier New", 11),
            bd=0,
            relief="flat",
        )
        menu.add_command(label="How to Use", command=lambda: InfoWindow(self, "How to Use", INSTRUCTIONS_TEXT))
        menu.add_command(label="Credits", command=lambda: InfoWindow(self, "Credits", CREDITS_TEXT))
        menu.add_separator()

        recent = load_recent()
        if recent:
            recent_menu = Menu(
                menu,
                tearoff=0,
                bg=BG_CARD,
                fg=TEXT_ON,
                activebackground=ACCENT,
                activeforeground="#111111",
                font=("Courier New", 11),
                bd=0,
                relief="flat",
            )
            for p in recent:
                recent_menu.add_command(
                    label=os.path.basename(p),
                    command=lambda pp=p: self._open_recent(pp),
                )
            menu.add_cascade(label="Recent Files", menu=recent_menu)

        menu.tk_popup(
            self._about_btn.winfo_rootx(),
            self._about_btn.winfo_rooty() + self._about_btn.winfo_height(),
        )

    def _open_recent(self, path: str):
        ext = path.lower()
        if ext.endswith(".xml"):
            self.file1_path.set(path)
            self.tabs.set("  Skeleton Merger  ")
        elif ext.endswith(".ymt"):
            self.donor_path_var.set(path)
            self._update_donor_slots(path)
            self.tabs.set("  YMT Asset Swapper  ")


class InfoWindow(ctk.CTkToplevel):
    def __init__(self, parent, title: str, body: str):
        super().__init__(parent)
        self.title(title)
        self.geometry("540x400")
        self.resizable(False, False)
        self.configure(fg_color=BG_DEEP)
        self.transient(parent)
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)

        make_label(self, title.upper(), size=15, color=ACCENT).pack(padx=24, pady=(22, 8), anchor="w")
        ctk.CTkFrame(self, height=1, fg_color=BORDER).pack(fill="x", padx=24, pady=(0, 12))

        box = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family="Courier New", size=12),
            fg_color=BG_FIELD,
            text_color=TEXT_ON,
            border_color=BORDER,
            border_width=1,
            corner_radius=3,
            wrap="word",
        )
        box.pack(fill="both", expand=True, padx=24, pady=(0, 24))
        box.insert("end", body.strip())
        box.configure(state="disabled")


if __name__ == "__main__":
    import ctypes
    
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ilyxrl.pedmechanic.v4")
    
    app = PedMechanicApp()
    
    app.iconbitmap("icon.ico")
    
    app.mainloop()
