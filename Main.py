"""GCodemaker-style desktop G-code editor and simulator."""

from __future__ import annotations

import math
import re
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


DARK = {
    "bg": "#15181c", "elev": "#1b1f24", "elev2": "#22272e",
    "hover": "#2a3038", "active": "#323a44", "editor": "#111418",
    "border": "#2d333b", "border_strong": "#3d444d", "text": "#d6dbe1",
    "strong": "#f0f3f6", "muted": "#8b949e", "accent": "#3ddc6a",
    "accent_strong": "#2fbf58", "accent_soft": "#1b3525", "danger": "#f2706b",
    "warning": "#e3b341", "grid": "#20252b", "cut": "#3ddc6a",
    "rapid": "#e5a331", "path": "#6d7885", "stock_top": "#798491",
    "stock_side": "#434b55",
}
LIGHT = {
    "bg": "#eef1f4", "elev": "#f8f9fb", "elev2": "#ffffff",
    "hover": "#e6eaef", "active": "#d9dfe6", "editor": "#ffffff",
    "border": "#d5dbe2", "border_strong": "#bcc4cd", "text": "#2a3139",
    "strong": "#11161c", "muted": "#626d78", "accent": "#22793a",
    "accent_strong": "#1a5f2d", "accent_soft": "#e6f1e8", "danger": "#c93c37",
    "warning": "#a8720b", "grid": "#e7eaee", "cut": "#22793a",
    "rapid": "#a8720b", "path": "#87919b", "stock_top": "#aeb7c0",
    "stock_side": "#737d88",
}

SAMPLE = """(G-Code Maker example - engraves a G)
(Flat end mill, stock top at Z0 - X0 Y0 at the bottom-left of the stock)
G21 G90 G17 G94
G0 Z6
M3 S18000

(Outline of the letter G)
G0 X16 Y12
G1 Z-1 F300
G1 X16 Y42 F1200
G1 X39 Y42
G2 X47 Y34 I0 J-8
G1 X47 Y30
G1 X35 Y30
G1 X35 Y35
G1 X39 Y35
G1 X39 Y37
G1 X24 Y37
G1 X24 Y17
G1 X39 Y17
G1 X39 Y23
G1 X35 Y23
G1 X35 Y27
G1 X47 Y27
G1 X47 Y16
G2 X39 Y8 I-8 J0
G1 X16 Y8
G1 X16 Y12
G0 Z6
M5
G0 X0 Y0
M30
"""

WORD = re.compile(r"([A-Z])\s*(-?\d+(?:\.\d*)?|-?\.\d+)", re.I)
COMMENT = re.compile(r"\([^)]*\)|;.*$")


@dataclass
class Motion:
    line: int
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    rapid: bool
    points: list[tuple[float, float, float]]
    feed: float = 300.0


def parse_program(source: str) -> tuple[list[Motion], dict[str, object]]:
    """Parse modal coordinates and common linear/XY-arc moves."""
    position = [0.0, 0.0, 0.0]
    absolute, scale, plane, feed, spindle = True, 1.0, "XY", 0.0, 0.0
    motion_mode = 0
    motions: list[Motion] = []
    for line_number, raw in enumerate(source.splitlines(), 1):
        clean = COMMENT.sub("", raw).strip().upper()
        if not clean:
            continue
        words = [(letter.upper(), float(number)) for letter, number in WORD.findall(clean)]
        if any(letter == "G" and value == 20 for letter, value in words):
            scale = 25.4
        if any(letter == "G" and value == 21 for letter, value in words):
            scale = 1.0
        if any(letter == "G" and value == 90 for letter, value in words):
            absolute = True
        if any(letter == "G" and value == 91 for letter, value in words):
            absolute = False
        if any(letter == "G" and value in (17, 18, 19) for letter, value in words):
            plane = {17: "XY", 18: "XZ", 19: "YZ"}[
                int(next(value for letter, value in words if letter == "G" and value in (17, 18, 19)))
            ]
        if any(letter == "G" and value in (0, 1, 2, 3) for letter, value in words):
            motion_mode = int(next(value for letter, value in words if letter == "G" and value in (0, 1, 2, 3)))
        for letter, value in words:
            if letter == "F":
                feed = value * scale
            elif letter == "S":
                spindle = value
        coordinates = {letter: value * scale for letter, value in words
                       if letter in "XYZIJKR"}
        if motion_mode not in (0, 1, 2, 3) or not any(axis in coordinates for axis in "XYZ"):
            continue
        start = tuple(position)
        end = list(position)
        for axis_index, axis in enumerate("XYZ"):
            if axis in coordinates:
                end[axis_index] = (
                    coordinates[axis] if absolute else end[axis_index] + coordinates[axis]
                )
        end_tuple = tuple(end)
        points = [start, end_tuple]
        if motion_mode in (2, 3):
            axis_u, axis_v, word_u, word_v = {
                "XY": (0, 1, "I", "J"),
                "XZ": (0, 2, "I", "K"),
                "YZ": (1, 2, "J", "K"),
            }[plane]
            offset_u = coordinates.get(word_u, 0.0)
            offset_v = coordinates.get(word_v, 0.0)
            if "R" in coordinates and offset_u == 0 and offset_v == 0:
                radius = abs(coordinates["R"])
                dx = end[axis_u] - position[axis_u]
                dy = end[axis_v] - position[axis_v]
                chord = math.hypot(dx, dy)
                if 0 < chord <= 2 * radius:
                    height = math.sqrt(radius * radius - chord * chord / 4)
                    sign = -1 if (motion_mode == 2) == (coordinates["R"] > 0) else 1
                    offset_u = dx / 2 + sign * (-dy / chord) * height
                    offset_v = dy / 2 + sign * (dx / chord) * height
            center_u = position[axis_u] + offset_u
            center_v = position[axis_v] + offset_v
            start_angle = math.atan2(position[axis_v] - center_v,
                                     position[axis_u] - center_u)
            end_angle = math.atan2(end[axis_v] - center_v,
                                   end[axis_u] - center_u)
            clockwise = motion_mode == 2
            sweep = (end_angle - start_angle) % (2 * math.pi)
            if clockwise:
                sweep = sweep - 2 * math.pi if sweep else -2 * math.pi
            else:
                sweep = sweep or 2 * math.pi
            radius = math.hypot(position[axis_u] - center_u, position[axis_v] - center_v)
            segments = max(8, min(96, int(abs(sweep) * max(radius, 1) / 2)))
            points = []
            for step in range(segments + 1):
                fraction = step / segments
                angle = start_angle + sweep * fraction
                point = [position[index] + (end[index] - position[index]) * fraction
                         for index in range(3)]
                point[axis_u] = center_u + math.cos(angle) * radius
                point[axis_v] = center_v + math.sin(angle) * radius
                points.append(tuple(point))
            points[0], points[-1] = start, end_tuple
        motions.append(Motion(line_number, start, end_tuple, motion_mode == 0, points, feed))
        position = end
    return motions, {"units": "mm" if scale == 1 else "inch", "scale": scale,
                     "absolute": absolute, "plane": plane, "feed": feed,
                     "spindle": spindle}


class CodeEditor(tk.Frame):
    def __init__(self, master: tk.Misc, colors: dict[str, str], changed):
        super().__init__(master, background=colors["editor"])
        self.colors = colors
        self.changed_callback = changed
        self.line_numbers = tk.Canvas(self, width=48, highlightthickness=0, bd=0)
        self.text = tk.Text(
            self, wrap="none", undo=True, autoseparators=True, maxundo=-1,
            borderwidth=0, highlightthickness=0, padx=8, pady=5,
            font=("DejaVu Sans Mono", 11), insertwidth=2, spacing1=0, spacing3=0,
            tabs=("2.4c",), background=colors["editor"], foreground=colors["text"],
            insertbackground=colors["text"], selectbackground=colors["active"],
        )
        self.scroll_y = tk.Scrollbar(
            self, orient="vertical", command=self._scroll_y, bg=colors["elev2"],
            troughcolor=colors["editor"], activebackground=colors["hover"],
            highlightbackground=colors["editor"], bd=0, width=12,
        )
        self.scroll_x = tk.Scrollbar(
            self, orient="horizontal", command=self.text.xview, bg=colors["elev2"],
            troughcolor=colors["editor"], activebackground=colors["hover"],
            highlightbackground=colors["editor"], bd=0, width=12,
        )
        self.text.configure(yscrollcommand=self._sync_scroll, xscrollcommand=self.scroll_x.set)
        self.line_numbers.grid(row=0, column=0, sticky="ns")
        self.text.grid(row=0, column=1, sticky="nsew")
        self.scroll_y.grid(row=0, column=2, sticky="ns")
        self.scroll_x.grid(row=1, column=1, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<KeyRelease>", self._refresh)
        self.text.bind("<MouseWheel>", self._mousewheel)
        self.text.bind("<Button-4>", lambda _event: self.text.yview_scroll(-1, "units"))
        self.text.bind("<Button-5>", lambda _event: self.text.yview_scroll(1, "units"))
        self.text.tag_configure("comment", foreground="#86a4a4", font=("DejaVu Sans Mono", 11, "italic"))
        self.text.tag_configure("gcode", foreground=colors["accent"], font=("DejaVu Sans Mono", 11, "bold"))
        self.text.tag_configure("mcode", foreground="#f2a76f")
        self.text.tag_configure("axis", foreground="#8ab4f8")
        self.text.tag_configure("number", foreground=colors["text"])
        self.text.tag_configure("current", background="#3a341f")
        self.text.edit_modified(False)
        self._refresh()

    def _mousewheel(self, event):
        self.text.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _scroll_y(self, *args):
        self.text.yview(*args)
        self._draw_numbers()

    def _sync_scroll(self, first, last):
        self.scroll_y.set(first, last)
        self._draw_numbers()

    def _draw_numbers(self):
        self.line_numbers.configure(background=self.colors["editor"])
        self.line_numbers.delete("all")
        index = self.text.index("@0,0")
        while True:
            info = self.text.dlineinfo(index)
            if info is None:
                break
            y = info[1]
            row = int(index.split(".")[0])
            color = self.colors["muted"]
            if row == int(self.text.index("insert").split(".")[0]):
                color = self.colors["text"]
            self.line_numbers.create_text(
                40, y + info[3] / 2, anchor="e", text=str(row),
                fill=color, font=("DejaVu Sans Mono", 10),
            )
            index = self.text.index(f"{index}+1line")

    def _on_modified(self, _event=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.changed_callback()
            self.after_idle(self._refresh)

    def _refresh(self, _event=None):
        for tag in ("comment", "gcode", "mcode", "axis", "number", "current"):
            self.text.tag_remove(tag, "1.0", "end")
        content = self.text.get("1.0", "end-1c")
        for match in re.finditer(r"\([^)]*\)|;.*$", content, re.M):
            self.text.tag_add("comment", f"1.0+{match.start()}c", f"1.0+{match.end()}c")
        comment_spans = [(m.start(), m.end()) for m in re.finditer(r"\([^)]*\)|;.*$", content, re.M)]
        for match in re.finditer(r"(?<![A-Z])([GMT])\s*(\d+(?:\.\d+)?)", content, re.I):
            if any(start <= match.start() < end for start, end in comment_spans):
                continue
            self.text.tag_add("gcode" if match.group(1).upper() == "G" else "mcode",
                              f"1.0+{match.start()}c", f"1.0+{match.end()}c")
        for match in re.finditer(r"\b[XYZIJKFS]\s*-?\d+(?:\.\d*)?", content, re.I):
            if any(start <= match.start() < end for start, end in comment_spans):
                continue
            self.text.tag_add("axis", f"1.0+{match.start()}c", f"1.0+{match.start()+1}c")
            self.text.tag_add("number", f"1.0+{match.start()+1}c", f"1.0+{match.end()}c")
        self._draw_numbers()

    def set_value(self, value: str):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        self.text.edit_modified(False)
        self._refresh()

    def value(self) -> str:
        return self.text.get("1.0", "end-1c")

    def highlight_line(self, line: int):
        self.text.tag_remove("current", "1.0", "end")
        if line > 0:
            self.text.tag_add("current", f"{line}.0", f"{line}.end")
            self.text.see(f"{line}.0")
        self._draw_numbers()


class ToolpathViewer(tk.Canvas):
    def __init__(self, master: tk.Misc, colors: dict[str, str], status_callback):
        super().__init__(master, background=colors["editor"], highlightthickness=0, bd=0)
        self.colors = colors
        self.status_callback = status_callback
        self.motions: list[Motion] = []
        self.cursor = 0
        self.camera = "Isometric"
        self.azimuth, self.elevation = -math.pi / 4, math.pi / 4.7
        self.scale, self.offset_x, self.offset_y = 1.0, 0.0, 0.0
        self.drag_origin = None
        self.drag_mode = None
        self.pan_mode = False
        self.show_grid = self.show_rapids = self.show_stock = self.show_info = True
        self.fit_pending = True
        self.bind("<Configure>", self._on_resize)
        self.bind("<ButtonPress-1>", self._start_rotate)
        self.bind("<B1-Motion>", self._drag_rotate)
        self.bind("<ButtonRelease-1>", self._end_drag)
        self.bind("<ButtonPress-2>", self._start_pan)
        self.bind("<B2-Motion>", self._drag_pan)
        self.bind("<ButtonPress-3>", self._start_pan)
        self.bind("<B3-Motion>", self._drag_pan)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda _event: self.zoom(1.12))
        self.bind("<Button-5>", lambda _event: self.zoom(1 / 1.12))
        for face, view in (("cube-top", "Top"), ("cube-front", "Front"),
                           ("cube-right", "Right")):
            self.tag_bind(face, "<Button-1>",
                          lambda _event, name=view: self._select_cube_view(name))

    def set_program(self, motions: list[Motion], cursor: int):
        self.motions, self.cursor = motions, cursor
        if self.fit_pending:
            self.fit()
        self.redraw()

    def set_cursor(self, cursor: int):
        self.cursor = cursor
        self.redraw()

    def _on_resize(self, _event=None):
        if self.fit_pending:
            self.after_idle(self.fit)
        else:
            self.redraw()

    def _camera_angles(self, name: str):
        names = {
            "Isometric": (-math.pi / 4, math.atan(1 / math.sqrt(2))),
            "Top": (0, math.pi / 2 - 0.001), "Bottom": (0, -math.pi / 2 + 0.001),
            "Front": (-math.pi / 2, 0), "Back": (math.pi / 2, 0),
            "Right": (0, 0), "Left": (math.pi, 0),
        }
        return names.get(name, (self.azimuth, self.elevation))

    def set_view(self, name: str):
        self.camera = name
        self.azimuth, self.elevation = self._camera_angles(name)
        self.fit()

    def _project(self, point):
        x, y, z = point
        az, el = self.azimuth, self.elevation
        right = (-math.sin(az) * x + math.cos(az) * y)
        up = (-math.sin(el) * math.cos(az) * x
              - math.sin(el) * math.sin(az) * y + math.cos(el) * z)
        return right, up

    def _bounds(self):
        points = [point for move in self.motions for point in (move.start, move.end)]
        if not points:
            return (0, 100, 0, 70, -8, 8)
        return (
            min(0, min(p[0] for p in points) - 5), max(100, max(p[0] for p in points) + 5),
            min(0, min(p[1] for p in points) - 5), max(70, max(p[1] for p in points) + 5),
            min(min(p[2] for p in points), -8) - 2,
            max(max(p[2] for p in points), 0) + 3,
        )

    def fit(self):
        width, height = max(self.winfo_width(), 2), max(self.winfo_height(), 2)
        if width < 50 or height < 50:
            self.fit_pending = True
            return
        bounds = self._bounds()
        corners = [(x, y, z) for x in (bounds[0], bounds[1])
                   for y in (bounds[2], bounds[3]) for z in (bounds[4], bounds[5])]
        projected = [self._project(point) for point in corners]
        min_x, max_x = min(p[0] for p in projected), max(p[0] for p in projected)
        min_y, max_y = min(p[1] for p in projected), max(p[1] for p in projected)
        self.scale = min((width - 100) / max(max_x - min_x, 1),
                         (height - 150) / max(max_y - min_y, 1))
        self.offset_x = width / 2 - (max_x + min_x) * self.scale / 2
        self.offset_y = height / 2 + (max_y + min_y) * self.scale / 2 + 8
        self.fit_pending = False
        self.redraw()

    def reset_view(self):
        self.azimuth, self.elevation = self._camera_angles("Isometric")
        self.camera = "Isometric"
        self.fit()

    def zoom(self, factor: float):
        x, y = self.winfo_width() / 2, self.winfo_height() / 2
        self.offset_x = x + (self.offset_x - x) * factor
        self.offset_y = y + (self.offset_y - y) * factor
        self.scale *= factor
        self.redraw()

    def _start_rotate(self, event):
        self.drag_origin = (event.x, event.y)
        self.drag_mode = "pan" if self.pan_mode else "rotate"
        self.pan_mode = False
        self.configure(cursor="fleur")

    def _drag_rotate(self, event):
        if self.drag_origin:
            if self.drag_mode == "pan":
                self._drag_pan(event)
                return
            dx, dy = event.x - self.drag_origin[0], event.y - self.drag_origin[1]
            self.azimuth -= dx * 0.008
            self.elevation = max(-1.5, min(1.5, self.elevation + dy * 0.008))
            self.camera = "Custom"
            self.drag_origin = event.x, event.y
            self.redraw()

    def activate_pan(self):
        self.pan_mode = True
        self.status_callback("Pan mode — drag in the preview")

    def _start_pan(self, event):
        self.drag_origin, self.drag_mode = (event.x, event.y), "pan"
        self.configure(cursor="fleur")

    def _drag_pan(self, event):
        if self.drag_origin:
            self.offset_x += event.x - self.drag_origin[0]
            self.offset_y += event.y - self.drag_origin[1]
            self.drag_origin = event.x, event.y
            self.redraw()

    def _end_drag(self, _event):
        self.drag_origin = self.drag_mode = None
        self.configure(cursor="")

    def _wheel(self, event):
        self.zoom(1.12 if event.delta > 0 else 1 / 1.12)
        return "break"

    def redraw(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 50 or height < 50:
            return
        if self.show_grid:
            self._draw_grid()
        self._draw_stock()
        for index, move in enumerate(self.motions):
            if move.rapid and not self.show_rapids:
                continue
            color = self.colors["rapid"] if move.rapid else self.colors["cut"]
            if index >= self.cursor:
                color = "#b38237" if move.rapid else "#27a758"
            if len(move.points) > 1:
                coords = []
                for point in move.points:
                    coords.extend(self._screen(point))
                self.create_line(*coords, fill=color, width=2 if index < self.cursor else 1.5,
                                 dash=(5, 4) if move.rapid else (), smooth=False)
        if self.motions:
            position = self.motions[-1].end
            if self.cursor < len(self.motions):
                position = self.motions[self.cursor].start if self.cursor == 0 else self.motions[self.cursor - 1].end
            self._draw_tool(position)
        self._draw_axis_gizmo()
        self._draw_orientation_cube()
        if self.show_info:
            self._draw_info()

    def _screen(self, point):
        x, y = self._project(point)
        return self.offset_x + self.scale * x, self.offset_y - self.scale * y

    def _draw_grid(self):
        bounds = self._bounds()
        size = max(10, math.ceil(max(bounds[1] - bounds[0], bounds[3] - bounds[2]) / 10) * 10)
        extent = min(max(size, 80), 500)
        grid_color = self.colors["grid"]
        for value in range(-extent, extent + 1, 10):
            for start, end in (((value, -extent, -8), (value, extent, -8)),
                               ((-extent, value, -8), (extent, value, -8))):
                self.create_line(*self._screen(start), *self._screen(end), fill=grid_color, width=1)

    def _draw_stock(self):
        if not self.show_stock:
            return
        b = self._bounds()
        x0, x1 = 0, b[1]
        y0, y1 = 0, b[3]
        corners_top = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)]
        corners_bottom = [(x, y, -8) for x, y, _ in corners_top]
        top = [value for point in corners_top for value in self._screen(point)]
        back_side = [value for point in (corners_top[0], corners_top[3],
                                          corners_bottom[3], corners_bottom[0])
                     for value in self._screen(point)]
        right_side = [value for point in (corners_top[1], corners_top[2],
                                           corners_bottom[2], corners_bottom[1])
                      for value in self._screen(point)]
        self.create_polygon(*back_side, fill=self.colors["stock_side"],
                            outline=self.colors["border_strong"], width=1)
        self.create_polygon(*right_side, fill=self.colors["stock_side"],
                            outline=self.colors["border_strong"], width=1)
        self.create_polygon(*top, fill=self.colors["stock_top"],
                            outline=self.colors["border_strong"], width=1)

    def _draw_tool(self, position):
        x, y = self._screen(position)
        size = max(5, min(12, self.scale * 0.4))
        self.create_line(x, y - size * 4, x, y - size, fill="#7fa7bb", width=5)
        self.create_line(x, y - size, x, y + size, fill="#d2a52c", width=5)
        self.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#f3f5f7", outline="")

    def _draw_axis_gizmo(self):
        x0, y0 = 34, self.winfo_height() - 34
        for axis, vector, color in (
            ("X", (1, 0, 0), "#f2706b"), ("Y", (0, 1, 0), "#4fc27b"),
            ("Z", (0, 0, 1), "#6ca9f5"),
        ):
            x1, y1 = self._screen(vector)
            factor = 20 / max(math.hypot(x1 - self.offset_x, y1 - self.offset_y), 0.01)
            px, py = x0 + (x1 - self.offset_x) * factor, y0 - (y1 - self.offset_y) * factor
            self.create_line(x0, y0, px, py, fill=color, width=2, arrow=tk.LAST)
            self.create_text(px, py, text=axis, fill=color, font=("DejaVu Sans", 9, "bold"))

    def _draw_orientation_cube(self):
        cx, cy = self.winfo_width() - 58, 60
        top = [(cx, cy - 44), (cx + 44, cy - 22), (cx, cy), (cx - 44, cy - 22)]
        front = [(cx - 44, cy - 22), (cx, cy), (cx, cy + 44), (cx - 44, cy + 22)]
        right = [(cx, cy), (cx + 44, cy - 22), (cx + 44, cy + 22), (cx, cy + 44)]
        faces = (
            ("cube-top", top, "TOP", "#303943"),
            ("cube-front", front, "FRONT", "#252c34"),
            ("cube-right", right, "RIGHT", "#1e252c"),
        )
        for tag, polygon, label, fill in faces:
            coords = [value for point in polygon for value in point]
            self.create_polygon(*coords, fill=fill, outline=self.colors["border_strong"],
                                width=1, tags=(tag,))
            x = cx if tag == "cube-top" else cx - 22 if tag == "cube-front" else cx + 22
            y = cy - 22 if tag == "cube-top" else cy + 1
            self.create_text(x, y, text=label, fill=self.colors["text"],
                             font=("DejaVu Sans", 8, "bold"),
                             angle=0 if tag == "cube-top" else -25 if tag == "cube-front" else 25,
                             tags=(tag,))

    def _select_cube_view(self, name):
        self.set_view(name)
        return "break"

    def _draw_info(self):
        bounds = self._bounds()
        info = (
            f"X     {bounds[0]:.1f} — {bounds[1]:.1f} mm    Δ {bounds[1]-bounds[0]:.1f} mm\n"
            f"Y     {bounds[2]:.1f} — {bounds[3]:.1f} mm    Δ {bounds[3]-bounds[2]:.1f} mm\n"
            f"Z     {bounds[4]:.1f} — {bounds[5]:.1f} mm    Δ {bounds[5]-bounds[4]:.1f} mm\n"
            f"\nCutting distance     {self._distance(False):,.1f} mm\n"
            f"Rapid distance       {self._distance(True):,.1f} mm\n"
            f"Estimated time       {self._duration()}\n"
            f"Stock                 {bounds[1]-bounds[0]:.1f} × {bounds[3]-bounds[2]:.1f} × 8 mm"
        )
        x1 = max(275, self.winfo_width() - 284)
        self.create_rectangle(x1, 120, x1 + 267, 272, fill=self.colors["elev"],
                              outline=self.colors["border"])
        self.create_text(x1 + 10, 131, anchor="nw", text=info, fill=self.colors["text"],
                         font=("DejaVu Sans Mono", 9), justify="left")

    def _distance(self, rapid: bool):
        distance = 0.0
        for move in self.motions:
            if move.rapid == rapid:
                distance += sum(math.dist(a, b) for a, b in zip(move.points, move.points[1:]))
        return distance

    def _duration(self):
        seconds = self._duration_seconds(len(self.motions))
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"

    def _duration_seconds(self, motion_count: int):
        return sum(
            math.dist(move.start, move.end) / (2500 if move.rapid else max(move.feed, 1)) * 60
            for move in self.motions[:motion_count]
        )


class GCodeMaker:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.colors = DARK
        self.theme = "dark"
        self.filename: Path | None = None
        self.dirty = False
        self.library_open = False
        self.motions: list[Motion] = []
        self.modal = {}
        self.line_count = 0
        self.sim_line = 0
        self.running = False
        self.speed = tk.StringVar(value="1×")
        self.show_status_info = True
        self.status_message = ""
        self.root.title("gcode_maker")
        self.root.geometry("1440x900")
        self.root.minsize(860, 520)
        self.root.configure(background=self.colors["bg"])
        self._build()
        self.editor.set_value(SAMPLE)
        self.on_code_change()
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self.exit)

    def _build(self):
        self.root.rowconfigure(2, weight=1)
        self.root.columnconfigure(0, weight=1)
        self._build_topbar()
        self._build_toolbar()
        self.workspace = tk.PanedWindow(
            self.root, orient="horizontal", sashwidth=5, sashrelief="flat",
            bd=0, background=self.colors["border"], opaqueresize=True,
        )
        self.workspace.grid(row=2, column=0, sticky="nsew")
        self.work_area = tk.PanedWindow(
            self.workspace, orient="horizontal", sashwidth=5, sashrelief="flat",
            bd=0, background=self.colors["border"], opaqueresize=True,
        )
        self.editor_pane = tk.Frame(self.work_area, background=self.colors["elev"])
        self.viewer_pane = tk.Frame(self.work_area, background=self.colors["elev"])
        self.work_area.add(self.editor_pane, minsize=250, stretch="always", width=720)
        self.work_area.add(self.viewer_pane, minsize=250, stretch="always", width=720)
        self.workspace.add(self.work_area, minsize=650, stretch="always")
        self._build_editor()
        self._build_viewer()
        self.library_pane = tk.Frame(self.workspace, background=self.colors["elev"], width=330)
        self.library_pane.pack_propagate(False)
        self._build_library()
        self._build_statusbar()

    def _label(self, parent, text, **kwargs):
        return tk.Label(parent, text=text, bg=self.colors["elev"], fg=self.colors["muted"],
                        font=("DejaVu Sans", 9, "bold"), **kwargs)

    def _button(self, parent, text, command, *, pressed=False, tooltip=None, **kwargs):
        options = {
            "text": text, "command": command, "bg": self.colors["elev"],
            "fg": self.colors["text"], "activebackground": self.colors["hover"],
            "activeforeground": self.colors["strong"], "bd": 0, "relief": "flat",
            "padx": 8, "pady": 4, "highlightthickness": 0,
            "font": ("DejaVu Sans", 9), "cursor": "hand2",
        }
        options.update(kwargs)
        button = tk.Button(parent, **options)
        button.bind("<Enter>", lambda _e: button.configure(bg=self.colors["hover"]))
        button.bind("<Leave>", lambda _e: button.configure(bg=self.colors["elev"]))
        if tooltip:
            self._tooltip(button, tooltip)
        return button

    def _tooltip(self, widget, text):
        popup = {"window": None}

        def show(_event=None):
            if popup["window"]:
                return
            tip = tk.Toplevel(self.root)
            tip.wm_overrideredirect(True)
            tip.configure(bg=self.colors["elev2"])
            tk.Label(tip, text=text, bg=self.colors["elev2"], fg=self.colors["text"],
                     padx=7, pady=4, font=("DejaVu Sans", 9)).pack()
            tip.geometry(f"+{widget.winfo_rootx()+8}+{widget.winfo_rooty()+widget.winfo_height()+4}")
            popup["window"] = tip

        def hide(_event=None):
            if popup["window"]:
                popup["window"].destroy()
                popup["window"] = None
        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")

    def _build_topbar(self):
        bar = tk.Frame(self.root, height=36, bg=self.colors["elev"])
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        brand = tk.Frame(bar, bg=self.colors["elev"])
        brand.pack(side="left", padx=(10, 8))
        tk.Label(brand, text="G.", fg=self.colors["accent"], bg=self.colors["elev"],
                 font=("DejaVu Sans", 15, "bold")).pack(side="left", padx=(0, 8))
        tk.Label(brand, text="gcode_maker", fg=self.colors["strong"], bg=self.colors["elev"],
                 font=("DejaVu Sans", 10, "bold")).pack(side="left")
        self.menubar = tk.Frame(bar, bg=self.colors["elev"])
        self.menubar.pack(side="left")
        menus = [
            ("File", self._file_menu), ("Edit", self._edit_menu),
            ("View", self._view_menu), ("Tools", self._tools_menu),
            ("Help", self._help_menu),
        ]
        for label, factory in menus:
            button = self._button(self.menubar, label, lambda: None, padx=8, pady=5)
            button.bind("<Button-1>", lambda event, f=factory: self._popup(event, f), add="")
        spacer = tk.Frame(bar, bg=self.colors["elev"])
        spacer.pack(side="left", fill="x", expand=True)
        self._button(bar, "▯", self.toggle_library, tooltip="Toggle library").pack(side="right", padx=5)
        self._button(bar, "☼", self.toggle_theme, tooltip="Toggle theme").pack(side="right", padx=5)
        self._button(bar, "☷", self.settings, tooltip="Settings").pack(side="right", padx=5)
        tk.Frame(bar, height=1, bg=self.colors["border"]).pack(side="bottom", fill="x")

    def _popup(self, event, factory):
        menu = factory()
        try:
            menu.tk_popup(event.widget.winfo_rootx(), event.widget.winfo_rooty() + event.widget.winfo_height())
        finally:
            menu.grab_release()

    def _menu(self):
        menu = tk.Menu(self.root, tearoff=False, bg=self.colors["elev2"],
                       fg=self.colors["text"], activebackground=self.colors["accent_soft"],
                       activeforeground=self.colors["strong"], bd=1,
                       relief="solid", font=("DejaVu Sans", 9))
        return menu

    def _file_menu(self):
        menu = self._menu()
        menu.add_command(label="New file", accelerator="Ctrl+N", command=self.new_file)
        menu.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_file)
        menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_file)
        menu.add_command(label="Save as…", accelerator="Ctrl+Shift+S", command=self.save_as)
        menu.add_separator()
        menu.add_command(label="Close tab", command=self.close_file)
        menu.add_command(label="Exit", command=self.exit)
        return menu

    def _edit_menu(self):
        menu = self._menu()
        for label, shortcut, event in (("Undo", "Ctrl+Z", "<<Undo>>"),
                                       ("Redo", "Ctrl+Y", "<<Redo>>")):
            menu.add_command(label=label, accelerator=shortcut,
                             command=lambda e=event: self.editor.text.event_generate(e))
        menu.add_separator()
        menu.add_command(label="Cut", accelerator="Ctrl+X",
                         command=lambda: self.editor.text.event_generate("<<Cut>>"))
        menu.add_command(label="Copy", accelerator="Ctrl+C",
                         command=lambda: self.editor.text.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", accelerator="Ctrl+V",
                         command=lambda: self.editor.text.event_generate("<<Paste>>"))
        menu.add_command(label="Select all", accelerator="Ctrl+A",
                         command=lambda: self.editor.text.tag_add("sel", "1.0", "end"))
        menu.add_separator()
        menu.add_command(label="Format G-code", accelerator="Ctrl+Shift+F",
                         command=self.format_code)
        return menu

    def _view_menu(self):
        menu = self._menu()
        menu.add_command(label="Toggle library", command=self.toggle_library)
        theme = self._menu()
        theme.add_command(label="Dark", command=lambda: self.set_theme("dark"))
        theme.add_command(label="Light", command=lambda: self.set_theme("light"))
        menu.add_cascade(label="Theme", menu=theme)
        menu.add_separator()
        menu.add_command(label="Fit to view", command=self.viewer.fit)
        menu.add_command(label="Reset view", command=self.viewer.reset_view)
        return menu

    def _tools_menu(self):
        menu = self._menu()
        menu.add_command(label="Play / Pause simulation", command=self.toggle_simulation)
        menu.add_command(label="Stop simulation", command=self.stop_simulation)
        menu.add_separator()
        menu.add_command(label="Show / hide rapid moves", command=self.toggle_rapids)
        menu.add_command(label="Show / hide stock", command=self.toggle_stock)
        menu.add_command(label="Show / hide grid", command=self.toggle_grid)
        return menu

    def _help_menu(self):
        menu = self._menu()
        menu.add_command(label="Keyboard shortcuts", command=self.shortcuts)
        menu.add_command(label="About", command=lambda: messagebox.showinfo(
            "About gcode_maker", "G-Code Maker — desktop editor and 3D toolpath simulator."))
        return menu

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=self.colors["elev"], height=38)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_propagate(False)
        for icon, command, tip in (
            ("♧", self.new_file, "New file (Ctrl+N)"),
            ("▱", self.open_file, "Open (Ctrl+O)"),
            ("▣", self.save_file, "Save (Ctrl+S)"),
            ("▤", self.save_as, "Save as (Ctrl+Shift+S)"),
        ):
            self._button(bar, icon, command, tooltip=tip).pack(side="left", padx=1)
        tk.Frame(bar, width=1, height=20, bg=self.colors["border"]).pack(side="left", padx=8)
        self._button(bar, "✣", self.format_code, tooltip="Format G-code").pack(side="left", padx=1)
        self.topbar_bottom = tk.Frame(bar, height=1, bg=self.colors["border"])
        self.topbar_bottom.pack(side="bottom", fill="x")

    def _build_editor(self):
        tabs = tk.Frame(self.editor_pane, height=34, bg=self.colors["elev"])
        tabs.pack(fill="x")
        self.tab = tk.Frame(tabs, bg=self.colors["editor"], padx=10)
        self.tab.pack(side="left", fill="y")
        tk.Label(self.tab, text="♧", bg=self.colors["editor"], fg=self.colors["accent"],
                 font=("DejaVu Sans", 10)).pack(side="left", padx=(0, 6))
        self.tab_name = tk.Label(self.tab, text="gcode-maker-example.nc",
                                 bg=self.colors["editor"], fg=self.colors["strong"],
                                 font=("DejaVu Sans", 9))
        self.tab_name.pack(side="left")
        self.dirty_indicator = tk.Label(self.tab, text="", bg=self.colors["editor"],
                                        fg=self.colors["warning"])
        self.dirty_indicator.pack(side="left", padx=5)
        tk.Frame(self.editor_pane, height=1, bg=self.colors["border"]).pack(fill="x")
        self.editor = CodeEditor(self.editor_pane, self.colors, self._editor_modified)
        self.editor.pack(fill="both", expand=True)

    def _build_viewer(self):
        header = tk.Frame(self.viewer_pane, height=34, bg=self.colors["elev"])
        header.pack(fill="x")
        header.pack_propagate(False)
        self._label(header, "PREVIEW").pack(side="left", padx=11)
        self.viewer = ToolpathViewer(self.viewer_pane, self.colors, self._set_status_message)
        self.viewer.pack(fill="both", expand=True)
        self._build_viewer_toolbar()
        self._build_simulation_bar()
        tk.Frame(self.viewer_pane, height=1, bg=self.colors["border"]).pack(fill="x")
        self.legend = tk.Frame(self.viewer, bg=self.colors["elev"])
        self.legend.place(x=9, rely=1, y=-38)
        for text, color, dash in (("Rapid (G0)", self.colors["rapid"], (4, 3)),
                                  ("Cut (G1/G2/G3)", self.colors["accent"], ())):
            swatch = tk.Canvas(self.legend, width=18, height=10, bg=self.colors["elev"],
                               highlightthickness=0)
            swatch.pack(side="left", padx=(6, 3), pady=6)
            swatch.create_line(0, 5, 17, 5, fill=color, width=2, dash=dash)
            tk.Label(self.legend, text=text, fg=self.colors["muted"], bg=self.colors["elev"],
                     font=("DejaVu Sans", 8)).pack(side="left", padx=(0, 7))

    def _build_viewer_toolbar(self):
        bar = tk.Frame(self.viewer, bg=self.colors["elev2"], highlightthickness=1,
                       highlightbackground=self.colors["border"])
        bar.place(x=9, y=8)
        self._button(bar, "⛶", self.viewer.fit, tooltip="Fit to view").pack(side="left", padx=1)
        tk.Frame(bar, width=1, height=16, bg=self.colors["border"]).pack(side="left", padx=3)
        for name, label in (("Top", "Top"), ("Front", "Front"), ("Right", "Side"),
                            ("Isometric", "Iso")):
            self._button(bar, label, lambda n=name: self.viewer.set_view(n)).pack(side="left", padx=1)
        tk.Frame(bar, width=1, height=16, bg=self.colors["border"]).pack(side="left", padx=3)
        self._button(bar, "◉", self.toggle_rapids, tooltip="Show/hide rapid moves (G0)",
                     fg=self.colors["accent"]).pack(side="left", padx=1)
        self._button(bar, "⌘", self.viewer.reset_view, tooltip="Drag to orbit").pack(side="left", padx=1)
        self._button(bar, "▦", self.toggle_grid, tooltip="Show/hide grid",
                     fg=self.colors["accent"]).pack(side="left", padx=1)
        self._button(bar, "ⓘ", self.toggle_info, tooltip="Program information",
                     fg=self.colors["accent"]).pack(side="left", padx=1)
        self._button(bar, "▾", self.show_views, tooltip="More views, zoom and pan").pack(side="left")

    def _build_simulation_bar(self):
        bar = tk.Frame(self.viewer_pane, height=38, bg=self.colors["elev"])
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.sim_buttons = tk.Frame(bar, bg=self.colors["elev"])
        self.sim_buttons.pack(side="left", padx=(8, 4))
        self._button(self.sim_buttons, "□", self.stop_simulation).pack(side="left")
        self._button(self.sim_buttons, "◁|", self.previous_motion).pack(side="left")
        self.play_button = self._button(self.sim_buttons, "▶", self.toggle_simulation,
                                        fg=self.colors["accent"])
        self.play_button.pack(side="left")
        self._button(self.sim_buttons, "|▷", self.next_motion).pack(side="left")
        self.progress = tk.Scale(
            bar, from_=0, to=100, orient="horizontal", showvalue=False,
            resolution=1, command=self.seek_simulation, bg=self.colors["elev"],
            troughcolor=self.colors["border_strong"], activebackground=self.colors["accent"],
            highlightthickness=0, bd=0, sliderlength=12, length=200,
        )
        self.progress.pack(side="left", fill="x", expand=True, padx=8)
        self.sim_time = tk.Label(bar, text="0:00 / 0:00", fg=self.colors["text"],
                                 bg=self.colors["elev"], font=("DejaVu Sans", 8))
        self.sim_time.pack(side="left", padx=4)
        self.sim_line_label = tk.Label(bar, text="Line 1", fg=self.colors["text"],
                                       bg=self.colors["elev"], font=("DejaVu Sans", 8))
        self.sim_line_label.pack(side="left", padx=7)
        self.speed_menu = ttk.Combobox(bar, textvariable=self.speed,
                                       values=("0.25×", "0.5×", "1×", "2×", "4×"),
                                       width=4, state="readonly", style="GCodeMaker.TCombobox")
        self.ttk_style = ttk.Style(self.root)
        self.ttk_style.theme_use("clam")
        self._style_speed_selector()
        self.speed_menu.pack(side="right", padx=7)
        self.speed_menu.bind("<<ComboboxSelected>>", lambda _e: None)

    def _build_library(self):
        header = tk.Frame(self.library_pane, height=34, bg=self.colors["elev"])
        header.pack(fill="x")
        header.pack_propagate(False)
        self._label(header, "LIBRARY").pack(side="left", padx=11)
        search = tk.Entry(self.library_pane, bg=self.colors["editor"], fg=self.colors["text"],
                          insertbackground=self.colors["text"], relief="flat",
                          highlightthickness=1, highlightbackground=self.colors["border_strong"])
        search.pack(fill="x", padx=8, pady=7)
        search.insert(0, "Search G-code")
        listbox = tk.Listbox(self.library_pane, bg=self.colors["elev"], fg=self.colors["text"],
                             selectbackground=self.colors["accent_soft"], bd=0,
                             highlightthickness=0, font=("DejaVu Sans Mono", 10))
        entries = (
            ("G0", "Rapid positioning"), ("G1", "Linear interpolation"),
            ("G2", "Clockwise arc"), ("G3", "Counterclockwise arc"),
            ("G17", "XY plane selection"), ("G20", "Inch units"),
            ("G21", "Millimeter units"), ("G28", "Return to home"),
            ("G90", "Absolute positioning"), ("G91", "Incremental positioning"),
            ("M3", "Spindle on clockwise"), ("M5", "Spindle stop"),
            ("M30", "End program"), ("F", "Feed rate"), ("S", "Spindle speed"),
            ("X Y Z", "Axis coordinates"),
        )
        for command, description in entries:
            listbox.insert("end", f"{command:<8} {description}")
        listbox.pack(fill="both", expand=True, padx=4)
        search.bind("<KeyRelease>", lambda _e: self._filter_library(search, listbox, entries))

    def _style_speed_selector(self):
        self.ttk_style.configure(
            "GCodeMaker.TCombobox", fieldbackground=self.colors["elev2"],
            background=self.colors["elev2"], foreground=self.colors["text"],
            arrowcolor=self.colors["text"], bordercolor=self.colors["border_strong"],
            lightcolor=self.colors["border_strong"], darkcolor=self.colors["border_strong"],
        )
        self.ttk_style.map(
            "GCodeMaker.TCombobox",
            fieldbackground=[("readonly", self.colors["elev2"])],
            foreground=[("readonly", self.colors["text"])],
        )

    def _filter_library(self, search, listbox, entries):
        query = search.get().strip().lower()
        listbox.delete(0, "end")
        for command, description in entries:
            if query in command.lower() or query in description.lower():
                listbox.insert("end", f"{command:<8} {description}")

    def _build_statusbar(self):
        bar = tk.Frame(self.root, height=24, bg=self.colors["elev"])
        bar.grid(row=3, column=0, sticky="ew")
        bar.grid_propagate(False)
        self.status_left = tk.Label(bar, text="Ln 1, Col 1   0 lines",
                                    bg=self.colors["elev"], fg=self.colors["muted"],
                                    font=("DejaVu Sans", 8), anchor="w")
        self.status_left.pack(side="left", padx=9)
        self.status_right = tk.Label(bar, text="mm (G21)    Plane G17 XY    Absolute (G90)    LF    Controller: Generic / ISO",
                                     bg=self.colors["elev"], fg=self.colors["muted"],
                                     font=("DejaVu Sans", 8), anchor="e")
        self.status_right.pack(side="right", padx=9)

    def _bind_shortcuts(self):
        for sequence, command in (
            ("<Control-n>", self.new_file), ("<Control-o>", self.open_file),
            ("<Control-s>", self.save_file), ("<Control-Shift-S>", self.save_as),
            ("<Control-Shift-f>", self.format_code), ("<F5>", self.toggle_simulation),
            ("<Shift-F5>", self.stop_simulation),
        ):
            self.root.bind_all(sequence, lambda _event, fn=command: (fn(), "break")[1])
        self.editor.text.bind("<KeyRelease>", self._cursor_changed, add="+")
        self.editor.text.bind("<ButtonRelease-1>", self._cursor_changed, add="+")
        self.editor.text.bind("<Control-a>", lambda _event: (
            self.editor.text.tag_add("sel", "1.0", "end"), "break"))

    def _cursor_changed(self, _event=None):
        line, column = self.editor.text.index("insert").split(".")
        self.status_left.configure(
            text=f"Ln {line}, Col {int(column)+1}    {self.line_count} lines"
        )
        return None

    def _set_status_message(self, message):
        self.status_message = message
        self.on_code_change()

    def on_code_change(self):
        if not hasattr(self, "editor"):
            return
        source = self.editor.value()
        self.motions, self.modal = parse_program(source)
        self.line_count = max(0, len(source.splitlines()))
        if self.sim_line > self.line_count:
            self.sim_line = self.line_count
        if hasattr(self, "viewer"):
            cursor = sum(move.line <= self.sim_line for move in self.motions)
            self.viewer.set_program(self.motions, cursor)
        if hasattr(self, "progress"):
            self.progress.configure(to=max(1, self.line_count))
            self.progress.set(min(self.sim_line, self.line_count))
            self.sim_line_label.configure(text=f"Line {max(1, self.sim_line)}")
            current = sum(move.line <= self.sim_line for move in self.motions)
            current_seconds = self.viewer._duration_seconds(current)
            total_seconds = self.viewer._duration_seconds(len(self.motions))
            self.sim_time.configure(
                text=f"{int(current_seconds//60)}:{int(current_seconds%60):02d} / "
                     f"{int(total_seconds//60)}:{int(total_seconds%60):02d}"
            )
        if hasattr(self, "status_right"):
            plane_code = {"XY": "G17", "XZ": "G18", "YZ": "G19"}.get(
                self.modal.get("plane", "XY"), "G17"
            )
            units = "mm (G21)" if self.modal.get("units") == "mm" else "inch (G20)"
            distance = "Absolute (G90)" if self.modal.get("absolute", True) else "Incremental (G91)"
            extra = f"    {self.status_message}" if self.status_message else ""
            self.status_right.configure(
                text=f"{units}    Plane {plane_code} {self.modal.get('plane', 'XY')}    {distance}    LF    Controller: Generic / ISO{extra}"
            )
        if hasattr(self, "tab_name"):
            name = self.filename.name if self.filename else "gcode-maker-example.nc"
            self.tab_name.configure(text=name)
            self.dirty_indicator.configure(text="●" if self.dirty else "")
        self._cursor_changed()

    def _set_dirty(self, value=True):
        self.dirty = value
        if hasattr(self, "tab_name"):
            self.on_code_change()

    def _editor_modified(self):
        self.dirty = True
        self.on_code_change()

    def new_file(self):
        if not self._confirm_discard():
            return
        self.filename = None
        self.editor.set_value("")
        self._set_dirty(False)
        self.sim_line = 0
        self.on_code_change()

    def open_file(self):
        if not self._confirm_discard():
            return
        filename = filedialog.askopenfilename(
            title="Open G-code", filetypes=(("G-code files", "*.nc *.gcode *.ngc *.tap *.cnc"),
                                            ("Text files", "*.txt"), ("All files", "*")),
        )
        if not filename:
            return
        try:
            source = Path(filename).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Open error", f"Could not open this file:\n{error}")
            return
        self.filename = Path(filename)
        self.editor.set_value(source)
        self._set_dirty(False)
        self.sim_line = 0
        self.on_code_change()

    def save_file(self):
        if self.filename is None:
            return self.save_as()
        return self._write_file(self.filename)

    def save_as(self):
        filename = filedialog.asksaveasfilename(
            title="Save G-code", defaultextension=".nc",
            filetypes=(("G-code files", "*.nc *.gcode *.ngc *.tap *.cnc"),
                       ("All files", "*")),
            initialfile=self.filename.name if self.filename else "untitled.nc",
        )
        if filename:
            return self._write_file(Path(filename))
        return False

    def _write_file(self, path: Path):
        try:
            path.write_text(self.editor.value(), encoding="utf-8", newline="")
        except OSError as error:
            messagebox.showerror("Save error", f"Could not save this file:\n{error}")
            return False
        self.filename = path
        self._set_dirty(False)
        return True

    def _confirm_discard(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved changes", "Save changes to the current file before continuing?"
        )
        if answer is None:
            return False
        return self.save_file() if answer else True

    def close_file(self):
        if self._confirm_discard():
            self.filename = None
            self.editor.set_value("")
            self.sim_line = 0
            self._set_dirty(False)
            self.on_code_change()

    def exit(self):
        if self._confirm_discard():
            self.root.destroy()

    def format_code(self):
        lines = []
        for raw in self.editor.value().splitlines():
            line = raw.strip()
            if line:
                line = re.sub(r"\s+", " ", line)
            lines.append(line)
        self.editor.set_value("\n".join(lines))
        self._set_dirty(True)

    def toggle_library(self):
        if self.library_open:
            self.workspace.forget(self.library_pane)
            self.library_open = False
        else:
            self.workspace.add(self.library_pane, minsize=260, width=330, stretch="never")
            self.library_open = True

    def set_theme(self, theme):
        if theme == self.theme:
            return
        old_colors = self.colors
        self.theme = theme
        self.colors = DARK if theme == "dark" else LIGHT
        palette = {value: self.colors[key] for key, value in old_colors.items()}
        for widget in self._all_widgets(self.root):
            updates = {}
            for option in ("background", "foreground", "activebackground", "activeforeground",
                           "highlightbackground", "insertbackground", "troughcolor"):
                try:
                    value = widget.cget(option)
                except tk.TclError:
                    continue
                if value in palette:
                    updates[option] = palette[value]
            if updates:
                try:
                    widget.configure(**updates)
                except tk.TclError:
                    pass
        self.root.configure(bg=self.colors["bg"])
        self.editor.colors = self.colors
        self.editor.line_numbers.configure(background=self.colors["editor"])
        self.editor.text.configure(
            background=self.colors["editor"], foreground=self.colors["text"],
            insertbackground=self.colors["text"],
        )
        self.editor.text.tag_configure("comment", foreground="#86a4a4")
        self.editor.text.tag_configure("gcode", foreground=self.colors["accent"])
        self.editor.text.tag_configure("mcode", foreground="#f2a76f")
        self.editor.text.tag_configure("axis", foreground="#8ab4f8")
        self.editor.text.tag_configure("number", foreground=self.colors["text"])
        self.editor.scroll_y.configure(
            bg=self.colors["elev2"], troughcolor=self.colors["editor"],
            activebackground=self.colors["hover"], highlightbackground=self.colors["editor"],
        )
        self.editor.scroll_x.configure(
            bg=self.colors["elev2"], troughcolor=self.colors["editor"],
            activebackground=self.colors["hover"], highlightbackground=self.colors["editor"],
        )
        self.viewer.colors = self.colors
        self.viewer.configure(background=self.colors["editor"])
        self.legend.configure(background=self.colors["elev"])
        self._style_speed_selector()
        self.viewer.redraw()
        self.editor._refresh()
        self.on_code_change()

    def toggle_theme(self):
        self.set_theme("light" if self.theme == "dark" else "dark")

    def _all_widgets(self, parent):
        for child in parent.winfo_children():
            yield child
            yield from self._all_widgets(child)

    def settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.geometry("440x280")
        dialog.configure(bg=self.colors["elev"])
        tk.Label(dialog, text="Settings", bg=self.colors["elev"], fg=self.colors["strong"],
                 font=("DejaVu Sans", 14, "bold")).pack(anchor="w", padx=18, pady=(18, 12))
        tk.Label(dialog, text="Appearance", bg=self.colors["elev"], fg=self.colors["muted"],
                 font=("DejaVu Sans", 9, "bold")).pack(anchor="w", padx=18, pady=(8, 4))
        row = tk.Frame(dialog, bg=self.colors["elev"])
        row.pack(fill="x", padx=18)
        self._button(row, "Dark theme", lambda: self.set_theme("dark")).pack(side="left")
        self._button(row, "Light theme", lambda: self.set_theme("light")).pack(side="left", padx=8)
        tk.Label(dialog, text="3D preview", bg=self.colors["elev"], fg=self.colors["muted"],
                 font=("DejaVu Sans", 9, "bold")).pack(anchor="w", padx=18, pady=(20, 4))
        tk.Label(dialog, text="Drag to orbit · Right-drag to pan · Mouse wheel to zoom",
                 bg=self.colors["elev"], fg=self.colors["text"],
                 font=("DejaVu Sans", 9)).pack(anchor="w", padx=18)
        self._button(dialog, "Close", dialog.destroy).pack(anchor="e", padx=18, pady=18)

    def toggle_simulation(self):
        if self.running:
            self.running = False
            self.play_button.configure(text="▶")
        else:
            if not self.motions:
                return
            if self.sim_line >= self.line_count:
                self.sim_line = 0
            self.running = True
            self.play_button.configure(text="Ⅱ")
            self._advance_simulation()

    def _advance_simulation(self):
        if not self.running:
            return
        if self.sim_line >= self.line_count:
            self.running = False
            self.play_button.configure(text="▶")
            return
        self.sim_line += 1
        self._sync_simulation()
        speed = float(self.speed.get().replace("×", ""))
        self.root.after(max(20, int(75 / speed)), self._advance_simulation)

    def _sync_simulation(self):
        motion_cursor = sum(move.line <= self.sim_line for move in self.motions)
        self.viewer.set_cursor(motion_cursor)
        self.editor.highlight_line(self.sim_line)
        self.sim_line_label.configure(text=f"Line {max(1, self.sim_line)}")
        self.progress.set(min(self.sim_line, self.line_count))
        current_seconds = self.viewer._duration_seconds(motion_cursor) if hasattr(
            self.viewer, "_duration_seconds") else 0
        total_seconds = self.viewer._duration_seconds(len(self.motions)) if hasattr(
            self.viewer, "_duration_seconds") else 0
        self.sim_time.configure(
            text=f"{int(current_seconds//60)}:{int(current_seconds%60):02d} / "
                 f"{int(total_seconds//60)}:{int(total_seconds%60):02d}"
        )

    def seek_simulation(self, value):
        if not hasattr(self, "editor"):
            return
        self.sim_line = int(float(value))
        self._sync_simulation()

    def stop_simulation(self):
        self.running = False
        self.play_button.configure(text="▶")
        self.sim_line = 0
        self._sync_simulation()

    def previous_motion(self):
        target = self.sim_line - 1
        for move in reversed(self.motions):
            if move.line < self.sim_line:
                target = move.line
                break
        self.sim_line = max(0, target)
        self._sync_simulation()

    def next_motion(self):
        for move in self.motions:
            if move.line > self.sim_line:
                self.sim_line = move.line
                break
        self._sync_simulation()

    def toggle_rapids(self):
        self.viewer.show_rapids = not self.viewer.show_rapids
        self.viewer.redraw()

    def toggle_stock(self):
        self.viewer.show_stock = not self.viewer.show_stock
        self.viewer.redraw()

    def toggle_grid(self):
        self.viewer.show_grid = not self.viewer.show_grid
        self.viewer.redraw()

    def toggle_info(self):
        self.viewer.show_info = not self.viewer.show_info
        self.viewer.redraw()

    def show_views(self):
        menu = self._menu()
        menu.add_command(label="Drag to orbit", state="disabled")
        menu.add_separator()
        for name in ("Front", "Back", "Left", "Right", "Top", "Bottom", "Isometric"):
            menu.add_command(label=name, command=lambda view=name: self.viewer.set_view(view))
        menu.add_separator()
        menu.add_command(label="Zoom in", command=lambda: self.viewer.zoom(1.2))
        menu.add_command(label="Zoom out", command=lambda: self.viewer.zoom(1 / 1.2))
        menu.add_command(label="Pan", command=self.viewer.activate_pan)
        menu.add_command(label="Fit to view", command=self.viewer.fit)
        menu.add_command(label="Reset view", command=self.viewer.reset_view)
        menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        menu.grab_release()

    def shortcuts(self):
        messagebox.showinfo(
            "Keyboard shortcuts",
            "Ctrl+N    New file\nCtrl+O    Open file\nCtrl+S    Save\n"
            "Ctrl+Shift+S    Save as\nCtrl+Shift+F    Format G-code\n"
            "Ctrl+Z / Ctrl+Y    Undo / Redo\nF5    Play / Pause\nShift+F5    Stop",
        )


def main():
    root = tk.Tk()
    GCodeMaker(root)
    root.mainloop()


if __name__ == "__main__":
    main()
