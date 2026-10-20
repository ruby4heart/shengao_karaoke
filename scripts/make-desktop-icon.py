from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer
from PIL import Image
root=Path(__file__).resolve().parents[1];app=QApplication([])
image=QImage(256,256,QImage.Format.Format_RGBA8888);image.fill(Qt.GlobalColor.transparent)
painter=QPainter(image);QSvgRenderer(str(root/'desktop'/'assets'/'shengao.svg')).render(painter);painter.end()
data=bytes(image.bits());picture=Image.frombytes('RGBA',(256,256),data)
picture.save(root/'desktop'/'assets'/'shengao.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
