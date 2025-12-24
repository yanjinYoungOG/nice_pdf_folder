#!/usr/bin/env python3
"""
PyQt5 PDF Signature Editor with Text Box Feature
Add text boxes with PDF-matched font styles
"""

import sys
import os
import json
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QScrollArea, QSplitter, QListWidget,
    QListWidgetItem, QFrame, QFileDialog, QMessageBox, QStatusBar,
    QToolBar, QAction, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QGraphicsItem, QGraphicsTextItem, QGraphicsProxyWidget,
    QMenu, QFontDialog, QInputDialog, QTextEdit
)
from PyQt5.QtCore import Qt, QPoint, QRectF, pyqtSignal, QTimer, QSize
from PyQt5.QtGui import (
    QImage, QPixmap, QPainter, QPen, QColor, QIcon, QFont,
    QWheelEvent, QCursor, QTextDocument
)
from PyPDF2 import PdfReader, PdfWriter
import fitz  # PyMuPDF
import io
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import re

# Paths
PDF_PATH = "/home/user/下载/nice_pdf_folder/xxx.pdf"
SIGN_PNG = "/home/user/下载/nice_pdf_folder/Sign.png"
OUTPUT_PATH = "/home/user/下载/nice_pdf_folder/xxx_signed.pdf"
STATE_FILE = "/home/user/下载/nice_pdf_folder/ui_state.json"
TEXT_BOXES_FILE = "/home/user/下载/nice_pdf_folder/text_boxes.json"


# ==================== Font Detection Utilities ====================
class FontDetector:
    """Detect font properties from PDF text."""

    @staticmethod
    def detect_font_properties(pdf_path, page_num=0):
        """Detect common font properties from PDF page."""
        doc = fitz.open(pdf_path)
        page = doc[page_num]

        # Get text blocks with font info
        blocks = page.get_text("dict")
        font_properties = {
            'family': 'Helvetica',  # Default fallback
            'size': 12,             # Default fallback
            'color': (0, 0, 0)      # Default black
        }

        # Analyze fonts used in the document
        font_sizes = []
        font_names = []

        for block in blocks.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    for span in line.get("spans", []):
                        # Get font size
                        if "size" in span:
                            font_sizes.append(span["size"])

                        # Get font name
                        if "font" in span:
                            font_names.append(span["font"])

        doc.close()

        # Use most common font size
        if font_sizes:
            # Use median or most frequent
            font_properties['size'] = int(round(sum(font_sizes) / len(font_sizes)))

        # Map PDF font names to common fonts
        font_mapping = {
            'Helvetica': 'Helvetica',
            'Times-Roman': 'Times New Roman',
            'Arial': 'Arial',
            'Courier': 'Courier New',
            'SimSun': 'SimSun',  # Chinese font
            'SimHei': 'SimHei',  # Chinese bold font
        }

        if font_names:
            # Find most common font family
            from collections import Counter
            font_counts = Counter(font_names)
            most_common = font_counts.most_common(1)[0][0]

            # Try to match
            for pdf_font, qt_font in font_mapping.items():
                if pdf_font.lower() in most_common.lower():
                    font_properties['family'] = qt_font
                    break

        return font_properties


# ==================== Custom Text Widget ====================
class PDFTextWidget(QWidget):
    """Widget containing text edit for Chinese input support."""

    def __init__(self, text="", font_family="Helvetica", font_size=12, parent=None):
        super().__init__(parent)

        # Make widget transparent
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Create layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create text edit
        self.text_edit = QTextEdit()
        self.text_edit.setText(text)
        self.text_edit.setFrameStyle(QFrame.NoFrame)
        self.text_edit.setLineWidth(0)

        # Set font
        font = QFont(font_family, font_size)
        self.text_edit.setFont(font)

        # Transparent background with dashed border when focused
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                border: none;
                color: black;
            }
            QTextEdit:focus {
                border: 1px dashed #4A90E2;
            }
        """)

        # Enable input method support
        self.text_edit.setAttribute(Qt.WA_InputMethodEnabled, True)

        layout.addWidget(self.text_edit)

        # Store properties
        self._font_family = font_family
        self._font_size = font_size

    def get_text(self):
        """Get text content."""
        return self.text_edit.toPlainText()

    def set_text(self, text):
        """Set text content."""
        self.text_edit.setText(text)

    def set_font_properties(self, family, size):
        """Set font properties."""
        self._font_family = family
        self._font_size = size
        font = QFont(family, size)
        self.text_edit.setFont(font)

    def get_font_properties(self):
        """Get font properties."""
        return {
            'family': self._font_family,
            'size': self._font_size
        }

    def get_size_hint(self):
        """Get recommended size."""
        doc = self.text_edit.document()
        doc.setTextWidth(self.text_edit.width())
        return self.text_edit.sizeHint()

    def showEvent(self, event):
        """Handle show event - ensure focus for IME."""
        super().showEvent(event)
        # Make sure input method is enabled
        self.text_edit.setAttribute(Qt.WA_InputMethodEnabled, True)


# ==================== Custom Text Item ====================
class PDFTextBoxItem(QGraphicsProxyWidget):
    """Text box item using QWidget for proper Chinese input support."""

    def __init__(self, text="", font_family="Helvetica", font_size=12, parent=None):
        super().__init__(parent)

        # Create the text widget
        self._text_widget = PDFTextWidget(text, font_family, font_size)
        self.setWidget(self._text_widget)

        # Item flags
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setZValue(500)

        # Initial size
        self._text_widget.resize(200, 60)
        self.resize(200, 60)

        # Auto-resize when text changes
        self._text_widget.text_edit.textChanged.connect(self._auto_resize)

    def _auto_resize(self):
        """Auto resize widget based on content."""
        # Get document size
        doc = self._text_widget.text_edit.document()
        doc.setTextWidth(self._text_widget.text_edit.width())
        size = doc.size().toSize()

        # Add some padding
        new_width = max(100, size.width() + 20)
        new_height = max(30, size.height() + 10)

        # Limit maximum size
        new_width = min(new_width, 400)
        new_height = min(new_height, 300)

        self._text_widget.resize(new_width, new_height)
        self.resize(new_width, new_height)

    def set_font_properties(self, family, size):
        """Set font properties."""
        self._text_widget.set_font_properties(family, size)

    def get_font_properties(self):
        """Get font properties."""
        return self._text_widget.get_font_properties()

    def toPlainText(self):
        """Get plain text content."""
        return self._text_widget.get_text()

    def pos(self):
        """Get position."""
        return super().pos()

    def contextMenuEvent(self, event):
        """Show context menu."""
        menu = QMenu()

        edit_action = menu.addAction("✏️ Edit")
        delete_action = menu.addAction("🗑️ Delete")
        menu.addSeparator()
        font_action = menu.addAction("🔤 Change Font...")

        action = menu.exec_(event.screenPos())

        if action == edit_action:
            self._text_widget.text_edit.setFocus()
            self._text_widget.text_edit.selectAll()
        elif action == delete_action:
            # Remove from scene
            if self.scene():
                self.scene().removeItem(self)
        elif action == font_action:
            # Change font
            font, ok = QFontDialog.getFont(
                QFont(self._text_widget._font_family, self._text_widget._font_size),
                None,
                "Select Font"
            )
            if ok:
                self.set_font_properties(font.family(), font.pointSize())

    def to_dict(self, pdf_width=None, pdf_height=None, display_width=None, display_height=None):
        """Serialize to dictionary.

        Args:
            pdf_width: PDF page width (for coordinate conversion)
            pdf_height: PDF page height (for coordinate conversion)
            display_width: Display width (for coordinate conversion)
            display_height: Display height (for coordinate conversion)

        If display dimensions are provided, coordinates will be converted to PDF coordinates.
        Otherwise, scene coordinates are saved directly.
        """
        scene_x = self.pos().x()
        scene_y = self.pos().y()

        # Convert to PDF coordinates if dimensions provided
        if pdf_width and display_width:
            x = scene_x * (pdf_width / display_width)
            display_scale_x = pdf_width / display_width
        else:
            x = scene_x
            display_scale_x = 1.0

        if pdf_height and display_height:
            y = scene_y * (pdf_height / display_height)
            display_scale_y = pdf_height / display_height
        else:
            y = scene_y
            display_scale_y = 1.0

        return {
            'text': self.toPlainText(),
            'x': x,
            'y': y,
            'scene_x': scene_x,
            'scene_y': scene_y,
            'width': self.boundingRect().width(),
            'height': self.boundingRect().height(),
            'font_family': self._text_widget._font_family,
            'font_size': self._text_widget._font_size,
            'display_scale_x': display_scale_x,
            'display_scale_y': display_scale_y
        }

    @classmethod
    def from_dict(cls, data, display_width=None, display_height=None, pdf_width=None, pdf_height=None):
        """Create from dictionary.

        Args:
            data: Dictionary with text box data
            display_width: Current display width (for coordinate conversion)
            display_height: Current display height (for coordinate conversion)
            pdf_width: PDF page width (for coordinate conversion)
            pdf_height: PDF page height (for coordinate conversion)
        """
        item = cls(
            text=data.get('text', ''),
            font_family=data.get('font_family', 'Helvetica'),
            font_size=data.get('font_size', 12)
        )

        # Calculate position
        if 'scene_x' in data and 'scene_y' in data:
            # Use saved scene coordinates directly
            x = data.get('scene_x', 0)
            y = data.get('scene_y', 0)
        elif display_width and pdf_width and display_height and pdf_height:
            # Convert PDF coordinates to scene coordinates
            scale_x = data.get('display_scale_x', 1.0)
            scale_y = data.get('display_scale_y', 1.0)
            x = data.get('x', 0) / scale_x * (display_width / pdf_width)
            y = data.get('y', 0) / scale_y * (display_height / pdf_height)
        else:
            # Use saved coordinates directly (fallback)
            x = data.get('x', 0)
            y = data.get('y', 0)

        item.setPos(x, y)

        # Set size
        width = data.get('width', 200)
        height = data.get('height', 60)
        item._text_widget.resize(width, height)
        item.resize(width, height)

        return item


# ==================== Signature Item ====================
class SignatureItem(QGraphicsPixmapItem):
    """Draggable signature item."""

    def __init__(self, pixmap, parent=None):
        super().__init__(pixmap, parent)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setZValue(1000)
        self._pdf_bounds = QRectF(0, 0, 1000, 1000)

    def set_pdf_bounds(self, bounds):
        """Set the PDF page bounds."""
        self._pdf_bounds = bounds

    def itemChange(self, change, value):
        """Handle item position changes."""
        if change == QGraphicsItem.ItemPositionChange:
            new_pos = value
            rect = self.boundingRect()

            # Keep within bounds
            if new_pos.x() < 0:
                new_pos.setX(0)
            if new_pos.y() < 0:
                new_pos.setY(0)
            if new_pos.x() + rect.width() > self._pdf_bounds.width():
                new_pos.setX(self._pdf_bounds.width() - rect.width())
            if new_pos.y() + rect.height() > self._pdf_bounds.height():
                new_pos.setY(self._pdf_bounds.height() - rect.height())

            return new_pos

        return super().itemChange(change, value)


# ==================== PDF Graphics View ====================
class PDFGraphicsView(QGraphicsView):
    """Graphics view for displaying PDF with signature and text overlay."""

    page_changed = pyqtSignal(int)
    text_boxes_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene()
        self.setScene(self.scene)

        # View settings
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setBackgroundBrush(QColor(240, 240, 240))

        # State
        self.current_page = 0
        self.total_pages = 1
        self.pdf_width = 0
        self.pdf_height = 0
        self.pdf_pixmap_item = None
        self.signature_item = None
        self.text_boxes = []
        self.scroll_speed = 30

        # Text box mode
        self.text_box_mode = False
        self.detected_font = None

    def load_pdf_page(self, pdf_path, page_num):
        """Load a specific page from the PDF."""
        doc = fitz.open(pdf_path)
        page = doc[page_num]

        self.current_page = page_num
        self.total_pages = len(doc)

        # Get page dimensions
        rect = page.rect
        self.pdf_width = rect.width
        self.pdf_height = rect.height

        # Render page to image
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")

        # Create QPixmap
        pixmap = QPixmap()
        pixmap.loadFromData(img_data)

        # Clear and update scene
        self.scene.clear()
        self.pdf_pixmap_item = None
        self.text_boxes = []

        # Add PDF as background
        self.pdf_pixmap_item = self.scene.addPixmap(pixmap)
        self.pdf_pixmap_item.setZValue(0)

        # Set scene rect
        self.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())

        # Detect font from this page
        self.detected_font = FontDetector.detect_font_properties(pdf_path, page_num)

        doc.close()
        self.page_changed.emit(page_num)

    def add_signature(self, sign_path, position=None, scale=1.0):
        """Add signature to the PDF view."""
        pixmap = QPixmap(sign_path)
        if pixmap.isNull():
            return False

        # Scale signature
        scaled_pixmap = pixmap.scaled(
            int(pixmap.width() * scale),
            int(pixmap.height() * scale),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        # Remove existing signature
        if self.signature_item:
            self.scene.removeItem(self.signature_item)

        # Create new signature item
        self.signature_item = SignatureItem(scaled_pixmap)
        scene_rect = self.scene.sceneRect()
        self.signature_item.set_pdf_bounds(QRectF(0, 0, scene_rect.width(), scene_rect.height()))

        # Set position
        if position:
            self.signature_item.setPos(position)
        else:
            # Default position: bottom right
            self.signature_item.setPos(
                scene_rect.width() - scaled_pixmap.width() - 100,
                scene_rect.height() - scaled_pixmap.height() - 100
            )

        self.scene.addItem(self.signature_item)
        return True

    def add_text_box(self, position=None, text="", font_props=None):
        """Add a new text box."""
        if font_props is None:
            font_props = self.detected_font or {
                'family': 'Helvetica',
                'size': 12
            }

        text_item = PDFTextBoxItem(
            text=text,
            font_family=font_props.get('family', 'Helvetica'),
            font_size=font_props.get('size', 12)
        )

        if position:
            text_item.setPos(position)
        else:
            # Center of visible area
            text_item.setPos(200, 200)

        self.scene.addItem(text_item)
        self.text_boxes.append(text_item)

        # Auto-enable editing
        text_item._text_widget.text_edit.setFocus()
        text_item._text_widget.text_edit.selectAll()

        self.text_boxes_changed.emit()
        return text_item

    def get_text_boxes(self):
        """Get all text boxes."""
        # Refresh from scene
        self.text_boxes = [item for item in self.scene.items()
                          if isinstance(item, PDFTextBoxItem)]
        return self.text_boxes

    def get_signature_position(self):
        """Get current signature position."""
        # Check if signature item exists and is valid
        if self.signature_item is None:
            return None

        try:
            # Try to get the scene - this will fail if item is deleted
            scene = self.signature_item.scene()
            if scene is None:
                self.signature_item = None
                return None

            pos = self.signature_item.pos()
            return QPoint(int(pos.x()), int(pos.y()))
        except (RuntimeError, AttributeError):
            # Item was deleted or is invalid
            self.signature_item = None
        return None

    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel for smooth scrolling."""
        delta = event.angleDelta().y()
        scroll_distance = -delta

        v_scroll = self.verticalScrollBar()
        current_value = v_scroll.value()
        new_value = current_value + scroll_distance * self.scroll_speed // 120

        v_scroll.setValue(new_value)
        event.accept()

    def mousePressEvent(self, event):
        """Handle mouse press for creating text boxes."""
        if self.text_box_mode and event.button() == Qt.LeftButton:
            # Map to scene coordinates
            scene_pos = self.mapToScene(event.pos())

            # Create new text box
            self.add_text_box(position=scene_pos)

            # Exit text box mode
            self.text_box_mode = False
            self.setCursor(QCursor(Qt.ArrowCursor))
            return

        super().mousePressEvent(event)


# ==================== PDF Scroll Area Wrapper ====================
class PDFScrollArea(QWidget):
    """Wrapper for PDF view with scroll support."""

    page_changed = pyqtSignal(int)
    text_boxes_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = PDFGraphicsView()

        # Connect signals
        self.view.page_changed.connect(self.page_changed.emit)
        self.view.text_boxes_changed.connect(self.text_boxes_changed.emit)

        # Create a scroll area wrapper
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.view)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        layout.addWidget(self.scroll_area)

    def load_pdf_page(self, pdf_path, page_num):
        """Load PDF page."""
        self.view.load_pdf_page(pdf_path, page_num)

    def add_signature(self, sign_path, position=None, scale=1.0):
        """Add signature."""
        return self.view.add_signature(sign_path, position, scale)

    def add_text_box(self, position=None, text="", font_props=None):
        """Add text box."""
        return self.view.add_text_box(position, text, font_props)

    def get_text_boxes(self):
        """Get all text boxes."""
        return self.view.get_text_boxes()

    def get_signature_position(self):
        """Get signature position."""
        try:
            return self.view.get_signature_position()
        except Exception:
            return None

    def set_text_box_mode(self, enabled):
        """Enable/disable text box creation mode."""
        self.view.text_box_mode = enabled
        if enabled:
            self.view.setCursor(QCursor(Qt.CrossCursor))
        else:
            self.view.setCursor(QCursor(Qt.ArrowCursor))

    @property
    def signature_item(self):
        return self.view.signature_item

    @property
    def pdf_width(self):
        return self.view.pdf_width

    @property
    def pdf_height(self):
        return self.view.pdf_height

    @property
    def pixmap(self):
        if self.view.pdf_pixmap_item:
            return self.view.pdf_pixmap_item.pixmap()
        return None

    def verticalScrollBar(self):
        return self.scroll_area.verticalScrollBar()


# ==================== Settings Manager ====================
class SettingsManager:
    """Manage UI state and text boxes persistence."""

    @staticmethod
    def save_state(scroll_pos, signature_pos, zoom, current_page, total_pages):
        """Save UI state to JSON file."""
        state = {
            'scroll_position': scroll_pos,
            'signature_position': {'x': signature_pos.x(), 'y': signature_pos.y()} if signature_pos else None,
            'zoom_level': zoom,
            'current_page': current_page,
            'total_pages': total_pages,
            'timestamp': datetime.now().isoformat()
        }

        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
            return True, "保存成功"
        except Exception as e:
            return False, f"保存失败: {str(e)}"

    @staticmethod
    def load_state():
        """Load UI state from JSON file."""
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    @staticmethod
    def save_text_boxes(text_boxes, page_num):
        """Save text boxes to JSON file (supports multiple pages)."""
        # Load existing data
        all_data = {}
        if os.path.exists(TEXT_BOXES_FILE):
            try:
                with open(TEXT_BOXES_FILE, 'r') as f:
                    all_data = json.load(f)
            except Exception:
                all_data = {}

        # Update current page's text boxes
        all_data[str(page_num)] = {
            'page_num': page_num,
            'text_boxes': [tb.to_dict() for tb in text_boxes],
            'timestamp': datetime.now().isoformat()
        }

        try:
            with open(TEXT_BOXES_FILE, 'w') as f:
                json.dump(all_data, f, indent=2)
            return True
        except Exception as e:
            print(f"Failed to save text boxes: {e}")
            return False

    @staticmethod
    def save_text_boxes_from_dicts(text_boxes_dicts, page_num):
        """Save text boxes from dictionary list (supports multiple pages)."""
        # Load existing data
        all_data = {}
        if os.path.exists(TEXT_BOXES_FILE):
            try:
                with open(TEXT_BOXES_FILE, 'r') as f:
                    all_data = json.load(f)
            except Exception:
                all_data = {}

        # Update current page's text boxes
        all_data[str(page_num)] = {
            'page_num': page_num,
            'text_boxes': text_boxes_dicts,
            'timestamp': datetime.now().isoformat()
        }

        try:
            with open(TEXT_BOXES_FILE, 'w') as f:
                json.dump(all_data, f, indent=2)
            return True
        except Exception as e:
            print(f"Failed to save text boxes: {e}")
            return False

    @staticmethod
    def load_text_boxes(page_num=None):
        """Load text boxes from JSON file.
        If page_num is specified, only return text boxes for that page.
        Otherwise, return all pages' text boxes.
        """
        try:
            if os.path.exists(TEXT_BOXES_FILE):
                with open(TEXT_BOXES_FILE, 'r') as f:
                    all_data = json.load(f)

                if page_num is not None:
                    # Return only the specified page's data
                    page_key = str(page_num)
                    if page_key in all_data:
                        return all_data[page_key]
                    return None
                else:
                    # Return all data
                    return all_data
        except Exception:
            pass
        return None


# ==================== Control Panel ====================
class ControlPanel(QFrame):
    """Control panel with buttons."""

    scroll_requested = pyqtSignal(str)
    save_requested = pyqtSignal()
    save_all_requested = pyqtSignal()
    add_text_box_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QFrame {
                background-color: #2c3e50;
                border-radius: 5px;
            }
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 10px 15px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #21618c;
            }
            QLabel {
                color: white;
                font-size: 12px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # UP button
        self.up_button = QPushButton("▲ UP")
        self.up_button.clicked.connect(lambda: self.scroll_requested.emit('up'))
        layout.addWidget(self.up_button)

        # DOWN button
        self.down_button = QPushButton("▼ DOWN")
        self.down_button.clicked.connect(lambda: self.scroll_requested.emit('down'))
        layout.addWidget(self.down_button)

        # Text box button
        self.text_box_button = QPushButton("📝 New Content")
        self.text_box_button.setStyleSheet("""
            QPushButton {
                background-color: #9b59b6;
            }
            QPushButton:hover {
                background-color: #8e44ad;
            }
        """)
        self.text_box_button.clicked.connect(self.add_text_box_requested.emit)
        layout.addWidget(self.text_box_button)

        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label, 1)

        # Save button
        self.save_button = QPushButton("💾 SAVE")
        self.save_button.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
            }
            QPushButton:hover {
                background-color: #229954;
            }
        """)
        self.save_button.clicked.connect(self.save_all_requested.emit)
        layout.addWidget(self.save_button)

    def set_status(self, text):
        """Update status label."""
        self.status_label.setText(text)

    def set_text_box_mode(self, active):
        """Indicate text box mode."""
        if active:
            self.text_box_button.setText("✏️ Click to Add Text")
            self.text_box_button.setStyleSheet("""
                QPushButton {
                    background-color: #e74c3c;
                }
                QPushButton:hover {
                    background-color: #c0392b;
                }
            """)
        else:
            self.text_box_button.setText("📝 New Content")
            self.text_box_button.setStyleSheet("""
                QPushButton {
                    background-color: #9b59b6;
                }
                QPushButton:hover {
                    background-color: #8e44ad;
                }
            """)


# ==================== Thumbnail Widget ====================
class ThumbnailWidget(QListWidget):
    """Page thumbnail navigation."""

    page_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QSize(80, 100))
        self.setMaximumWidth(120)
        self.setStyleSheet("""
            QListWidget {
                background-color: #ecf0f1;
                border: none;
            }
            QListWidget::item {
                padding: 5px;
                margin: 2px;
                border-radius: 3px;
            }
            QListWidget::item:selected {
                background-color: #3498db;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #d5dbdb;
            }
        """)
        self.currentRowChanged.connect(self.on_item_changed)

    def load_thumbnails(self, pdf_path):
        """Generate page thumbnails."""
        self.clear()
        doc = fitz.open(pdf_path)

        for page_num in range(len(doc)):
            page = doc[page_num]

            # Render thumbnail
            mat = fitz.Matrix(0.3, 0.3)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")

            # Create QPixmap
            pixmap = QPixmap()
            pixmap.loadFromData(img_data)

            # Create list item
            item = QListWidgetItem(f"P{page_num + 1}")
            item.setIcon(QIcon(pixmap))
            item.setData(Qt.UserRole, page_num)
            self.addItem(item)

        doc.close()

    def on_item_changed(self, row):
        """Handle thumbnail selection."""
        if row >= 0:
            item = self.item(row)
            page_num = item.data(Qt.UserRole)
            self.page_selected.emit(page_num)

    def set_current_page(self, page_num):
        """Set current page highlight."""
        self.setCurrentRow(page_num)


# ==================== Main Window ====================
class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("📄 PDF Editor with Text Boxes")
        self.setGeometry(100, 100, 1200, 800)

        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QStatusBar {
                background-color: #2c3e50;
                color: white;
            }
        """)

        # Components
        self.pdf_viewer = None
        self.thumbnails = None
        self.control_panel = None
        self.current_page = 0
        self.total_pages = 1
        self.signature_scale = 0.3
        self.current_pdf_path = PDF_PATH

        self.init_ui()
        self.load_pdf()

    def init_ui(self):
        """Initialize the UI components."""
        # Create central widget
        central = QWidget()
        self.setCentralWidget(central)

        # Main layout
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create toolbar
        toolbar = QToolBar()
        toolbar.setStyleSheet("""
            QToolBar {
                background-color: #34495e;
                spacing: 5px;
            }
            QToolButton {
                background-color: transparent;
                color: white;
                border: none;
                padding: 5px;
            }
            QToolButton:hover {
                background-color: #2c3e50;
            }
        """)
        self.addToolBar(toolbar)

        # Add toolbar items
        open_action = QAction("📂 Open PDF", self)
        open_action.triggered.connect(self.open_pdf)
        toolbar.addAction(open_action)

        save_pdf_action = QAction("💾 Save Signed PDF", self)
        save_pdf_action.triggered.connect(self.save_signed_pdf)
        toolbar.addAction(save_pdf_action)

        save_text_action = QAction("📝 Save Text Boxes", self)
        save_text_action.triggered.connect(self.save_text_boxes_to_pdf)
        toolbar.addAction(save_text_action)

        toolbar.addSeparator()

        # Create splitter for main content
        splitter = QSplitter(Qt.Horizontal)

        # Left: Thumbnails
        self.thumbnails = ThumbnailWidget()
        self.thumbnails.page_selected.connect(self.go_to_page)
        splitter.addWidget(self.thumbnails)

        # Center: PDF viewer
        self.pdf_viewer = PDFScrollArea()
        self.pdf_viewer.page_changed.connect(self.on_page_changed)
        self.pdf_viewer.text_boxes_changed.connect(self.on_text_boxes_changed)
        splitter.addWidget(self.pdf_viewer)

        # Set splitter sizes
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([120, 900])

        main_layout.addWidget(splitter, 1)

        # Bottom: Control panel
        self.control_panel = ControlPanel()
        self.control_panel.scroll_requested.connect(self.on_scroll_request)
        self.control_panel.save_requested.connect(self.save_state)
        self.control_panel.save_all_requested.connect(self.save_signed_pdf)
        self.control_panel.add_text_box_requested.connect(self.toggle_text_box_mode)
        main_layout.addWidget(self.control_panel)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.update_status_bar()

    def load_pdf(self):
        """Load the PDF file."""
        self.load_pdf_with_path(self.current_pdf_path)

    def load_pdf_with_path(self, pdf_path):
        """Load PDF from specific path."""
        if not os.path.exists(pdf_path):
            QMessageBox.critical(self, "Error", f"PDF not found:\n{pdf_path}")
            return

        # Get total pages
        reader = PdfReader(pdf_path)
        self.total_pages = len(reader.pages)

        # Show last page (P7) by default - signature only appears here
        self.current_page = self.total_pages - 1

        # Load thumbnails
        self.thumbnails.load_thumbnails(pdf_path)

        # Load page
        self.pdf_viewer.load_pdf_page(pdf_path, self.current_page)

        # Add signature on last page (P7)
        if self.current_page == self.total_pages - 1 and os.path.exists(SIGN_PNG):
            self.pdf_viewer.add_signature(SIGN_PNG, scale=self.signature_scale)

        # Restore text boxes
        self.restore_text_boxes()

        # Update thumbnails selection
        self.thumbnails.set_current_page(self.current_page)

        self.update_status_bar()

    def open_pdf(self):
        """Open a PDF file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", os.path.dirname(self.current_pdf_path),
            "PDF Files (*.pdf)"
        )
        if file_path:
            self.current_pdf_path = file_path
            self.load_pdf_with_path(file_path)

    def go_to_page(self, page_num):
        """Navigate to specific page."""
        if 0 <= page_num < self.total_pages:
            # Save current text boxes before switching
            try:
                self.save_text_boxes_state()
            except Exception:
                pass

            self.pdf_viewer.load_pdf_page(self.current_pdf_path, page_num)

    def on_page_changed(self, page_num):
        """Handle page change."""
        self.current_page = page_num
        self.thumbnails.blockSignals(True)
        self.thumbnails.set_current_page(page_num)
        self.thumbnails.blockSignals(False)

        # Only show signature on last page (P7)
        if page_num == self.total_pages - 1 and os.path.exists(SIGN_PNG):
            try:
                # Check if signature exists and is valid
                if self.pdf_viewer.signature_item is None:
                    self.pdf_viewer.add_signature(SIGN_PNG, scale=self.signature_scale)
            except Exception:
                self.pdf_viewer.signature_item = None  # Reset if invalid

        # Restore text boxes for this page after delay
        QTimer.singleShot(100, self.restore_text_boxes)

        # Update status bar
        try:
            self.update_status_bar()
        except Exception:
            pass  # Ignore status bar errors

    def on_text_boxes_changed(self):
        """Handle text boxes change."""
        self.update_status_bar()

    def on_scroll_request(self, direction):
        """Handle scroll button clicks."""
        scroll_bar = self.pdf_viewer.verticalScrollBar()
        step = 50

        if direction == 'up':
            scroll_bar.setValue(scroll_bar.value() - step)
        elif direction == 'down':
            scroll_bar.setValue(scroll_bar.value() + step)

    def toggle_text_box_mode(self):
        """Toggle text box creation mode."""
        current_mode = self.pdf_viewer.view.text_box_mode
        new_mode = not current_mode
        self.pdf_viewer.set_text_box_mode(new_mode)
        self.control_panel.set_text_box_mode(new_mode)

        if new_mode:
            self.status_bar.showMessage("Click on PDF to add text box", 3000)
        else:
            self.status_bar.showMessage("", 1000)

    def save_text_boxes_state(self):
        """Save text boxes state to file."""
        text_boxes = self.pdf_viewer.get_text_boxes()

        # Get display and PDF dimensions for coordinate conversion
        display_pixmap = self.pdf_viewer.pixmap
        if display_pixmap:
            display_width = display_pixmap.width()
            display_height = display_pixmap.height()
            pdf_w = self.pdf_viewer.pdf_width
            pdf_h = self.pdf_viewer.pdf_height
        else:
            display_width = display_height = pdf_w = pdf_h = None

        # Convert text boxes to dict with coordinate conversion
        text_boxes_dicts = []
        for tb in text_boxes:
            tb_dict = tb.to_dict(pdf_w, pdf_h, display_width, display_height)
            text_boxes_dicts.append(tb_dict)

        SettingsManager.save_text_boxes_from_dicts(text_boxes_dicts, self.current_page)
        self.status_bar.showMessage("Text boxes saved", 2000)

    def save_text_boxes_to_pdf(self):
        """Save only text boxes to PDF (all pages)."""
        self.control_panel.set_status("⏳ Saving text boxes...")

        try:
            reader = PdfReader(self.current_pdf_path)
            writer = PdfWriter()

            # Save current page's text boxes first
            self.save_text_boxes_state()

            # Load all text boxes from file
            all_text_boxes = SettingsManager.load_text_boxes(page_num=None)
            if not all_text_boxes:
                all_text_boxes = {}

            for i, page in enumerate(reader.pages):
                has_content = False
                packet = io.BytesIO()
                page_obj = reader.pages[i]
                page_width = float(page_obj.mediabox[2])
                page_height = float(page_obj.mediabox[3])

                c = canvas.Canvas(packet, pagesize=(page_width, page_height))

                # Get text boxes for this page
                page_key = str(i)
                if page_key not in all_text_boxes:
                    writer.add_page(page)
                    continue

                page_text_boxes = all_text_boxes[page_key].get('text_boxes', [])

                # Add text boxes for this page (x, y are already in PDF coordinates)
                for tb_dict in page_text_boxes:
                    try:
                        tb_text = tb_dict.get('text', '')
                        tb_font_family = tb_dict.get('font_family', 'Helvetica')
                        tb_font_size = tb_dict.get('font_size', 12)
                        tb_pos_x = tb_dict.get('x', 0)
                        tb_pos_y = tb_dict.get('y', 0)

                        # Calculate final Y (reportlab coordinates from bottom)
                        final_y = page_height - tb_pos_y - tb_font_size

                        # Set font (fallback to Helvetica if font not found)
                        try:
                            c.setFont(tb_font_family, tb_font_size)
                        except:
                            c.setFont('Helvetica', tb_font_size)

                        c.setFillColorRGB(0, 0, 0)

                        # Draw text
                        c.drawString(tb_pos_x, final_y, tb_text)
                        has_content = True
                    except Exception as e:
                        print(f"Error adding text box: {e}")

                # Only save canvas if there's content
                if has_content:
                    c.save()
                    packet.seek(0)

                    watermark = PdfReader(packet)
                    if len(watermark.pages) > 0:
                        watermark_page = watermark.pages[0]
                        page_obj.merge_page(watermark_page)

                writer.add_page(page)

            with open(OUTPUT_PATH, "wb") as output_file:
                writer.write(output_file)

            self.control_panel.set_status("✓ Text Boxes Saved!")
            QMessageBox.information(self, "Success", f"Text boxes saved to PDF:\n{OUTPUT_PATH}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save text boxes:\n{str(e)}")
            self.control_panel.set_status("✗ Save Failed")
            import traceback
            traceback.print_exc()

    def restore_text_boxes(self):
        """Restore text boxes from file for current page."""
        data = SettingsManager.load_text_boxes(self.current_page)
        if not data:
            return

        # Get display and PDF dimensions for coordinate conversion
        display_pixmap = self.pdf_viewer.pixmap
        if display_pixmap:
            display_width = display_pixmap.width()
            display_height = display_pixmap.height()
            pdf_w = self.pdf_viewer.pdf_width
            pdf_h = self.pdf_viewer.pdf_height
        else:
            display_width = display_height = pdf_w = pdf_h = None

        for tb_data in data.get('text_boxes', []):
            text_box = PDFTextBoxItem.from_dict(tb_data, display_width, display_height, pdf_w, pdf_h)
            self.pdf_viewer.view.scene.addItem(text_box)
            self.pdf_viewer.view.text_boxes.append(text_box)

    def save_state(self):
        """Save current UI state."""
        scroll_pos = self.pdf_viewer.verticalScrollBar().value()
        signature_pos = self.pdf_viewer.get_signature_position()

        success, message = SettingsManager.save_state(
            scroll_pos, signature_pos, self.signature_scale,
            self.current_page, self.total_pages
        )

        if success:
            self.control_panel.set_status("✓ Saved")
            self.save_text_boxes_state()  # Also save text boxes
            self.status_bar.showMessage(f"State saved: {message}", 3000)
        else:
            QMessageBox.warning(self, "Save Failed", message)

    def restore_state(self):
        """Restore previous UI state."""
        state = SettingsManager.load_state()
        if not state:
            return

        # Restore page first
        if 'current_page' in state:
            page = state['current_page']
            if 0 <= page < self.total_pages:
                self.pdf_viewer.load_pdf_page(self.current_pdf_path, page)

        # Restore signature position after page is loaded
        if state.get('signature_position'):
            pos = state['signature_position']
            QTimer.singleShot(100, lambda: self.pdf_viewer.add_signature(
                SIGN_PNG,
                QPoint(pos['x'], pos['y']),
                self.signature_scale
            ))

        # Restore scroll position
        if 'scroll_position' in state:
            QTimer.singleShot(150, lambda: self.pdf_viewer.verticalScrollBar().setValue(state['scroll_position']))

        self.status_bar.showMessage("State restored", 3000)

    def save_signed_pdf(self):
        """Save the signed PDF with text boxes."""
        self.control_panel.set_status("⏳ Saving...")

        try:
            reader = PdfReader(self.current_pdf_path)
            writer = PdfWriter()

            # Save current page's text boxes first
            self.save_text_boxes_state()

            # Load all text boxes from file
            all_text_boxes = SettingsManager.load_text_boxes(page_num=None)
            if not all_text_boxes:
                all_text_boxes = {}

            # Get display pixmap for coordinate conversion (for signature)
            display_pixmap = self.pdf_viewer.pixmap
            if display_pixmap:
                display_width = display_pixmap.width()
                display_height = display_pixmap.height()
                pdf_w = self.pdf_viewer.pdf_width
                pdf_h = self.pdf_viewer.pdf_height
            else:
                display_width = display_height = pdf_w = pdf_h = None

            for i, page in enumerate(reader.pages):
                has_content = False
                packet = io.BytesIO()
                page_obj = reader.pages[i]
                page_width = float(page_obj.mediabox[2])
                page_height = float(page_obj.mediabox[3])

                c = canvas.Canvas(packet, pagesize=(page_width, page_height))

                # Get text boxes for this page
                page_key = str(i)
                if page_key in all_text_boxes:
                    page_text_boxes = all_text_boxes[page_key].get('text_boxes', [])

                    # Add text boxes for this page (x, y are already in PDF coordinates)
                    for tb_dict in page_text_boxes:
                        try:
                            tb_text = tb_dict.get('text', '')
                            tb_font_family = tb_dict.get('font_family', 'Helvetica')
                            tb_font_size = tb_dict.get('font_size', 12)
                            tb_pos_x = tb_dict.get('x', 0)
                            tb_pos_y = tb_dict.get('y', 0)

                            # Calculate final Y (reportlab coordinates from bottom)
                            final_y = page_height - tb_pos_y - tb_font_size

                            # Set font (fallback to Helvetica if font not found)
                            try:
                                c.setFont(tb_font_family, tb_font_size)
                            except:
                                c.setFont('Helvetica', tb_font_size)

                            c.setFillColorRGB(0, 0, 0)

                            # Draw text
                            c.drawString(tb_pos_x, final_y, tb_text)
                            has_content = True
                        except Exception as e:
                            print(f"Error adding text box: {e}")

                # Add signature if on current page (last page P7)
                if i == self.total_pages - 1 and self.pdf_viewer.signature_item:
                    try:
                        sig_item = self.pdf_viewer.signature_item
                        scene_pos = sig_item.pos()

                        sig_pixmap = sig_item.pixmap()
                        orig_pixmap = QPixmap(SIGN_PNG)
                        scale = sig_pixmap.width() / orig_pixmap.width()

                        img_reader = ImageReader(SIGN_PNG)
                        img_width, img_height = img_reader.getSize()

                        sig_width = img_width * scale
                        sig_height = img_height * scale

                        pdf_x = scene_pos.x() * (pdf_w / display_width)
                        pdf_y = scene_pos.y() * (pdf_h / display_height)

                        final_y = page_height - pdf_y - sig_height

                        c.drawImage(
                            SIGN_PNG,
                            pdf_x,
                            final_y,
                            sig_width,
                            sig_height,
                            preserveAspectRatio=True,
                            mask='auto'
                        )
                        has_content = True
                    except Exception as e:
                        print(f"Error adding signature: {e}")

                # Only save canvas if there's content
                if has_content:
                    c.save()
                    packet.seek(0)

                    watermark = PdfReader(packet)
                    if len(watermark.pages) > 0:
                        watermark_page = watermark.pages[0]
                        page_obj.merge_page(watermark_page)

                writer.add_page(page)

            with open(OUTPUT_PATH, "wb") as output_file:
                writer.write(output_file)

            self.control_panel.set_status("✓ PDF Saved!")
            QMessageBox.information(self, "Success", f"Signed PDF saved to:\n{OUTPUT_PATH}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save PDF:\n{str(e)}")
            self.control_panel.set_status("✗ Save Failed")
            import traceback
            traceback.print_exc()

    def update_status_bar(self):
        """Update status bar."""
        try:
            text_boxes = self.pdf_viewer.get_text_boxes()
            sig_pos = self.pdf_viewer.get_signature_position()

            pos_str = f"({sig_pos.x()}, {sig_pos.y()})" if sig_pos else "N/A"
            self.status_bar.showMessage(
                f"Page {self.current_page + 1} / {self.total_pages} | "
                f"Signature: {pos_str} | "
                f"Text Boxes: {len(text_boxes)}"
            )
        except Exception as e:
            # Fallback if there's any error
            self.status_bar.showMessage(
                f"Page {self.current_page + 1} / {self.total_pages}"
            )

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts."""
        if event.key() == Qt.Key_S and event.modifiers() & Qt.ControlModifier:
            self.save_signed_pdf()
        elif event.key() == Qt.Key_Up:
            self.on_scroll_request('up')
        elif event.key() == Qt.Key_Down:
            self.on_scroll_request('down')
        else:
            super().keyPressEvent(event)


# ==================== Application Entry ====================
def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
