"""Scalable application artwork drawn locally; no font-dependent symbols."""
from functools import lru_cache
import math
from PIL import Image, ImageDraw, ImageFilter
import customtkinter as ctk


@lru_cache(maxsize=64)
def artwork(kind, color='#369eff', tile=False):
    s = 4
    im = Image.new('RGBA', (64*s, 64*s))
    d = ImageDraw.Draw(im)
    def line(points, fill=color, width=3):
        d.line([(int(x*s), int(y*s)) for x,y in points], fill=fill, width=int(width*s), joint='curve')
    def box(rect, fill, radius=5):
        d.rounded_rectangle(tuple(int(v*s) for v in rect), radius=int(radius*s), fill=fill)
    def circle(rect, fill=None, outline=None, width=3):
        d.ellipse(tuple(int(v*s) for v in rect), fill=fill, outline=outline, width=int(width*s))
    if tile:
        mask = Image.new('L', im.size)
        ImageDraw.Draw(mask).rounded_rectangle((0,0,im.width-1,im.height-1), radius=14*s, fill=255)
        gradient = Image.new('RGBA', im.size)
        gd = ImageDraw.Draw(gradient)
        rgb = tuple(int(color[i:i+2],16) for i in (1,3,5))
        for y in range(im.height):
            factor = .26 - .12*y/im.height
            gd.line((0,y,im.width,y), fill=tuple(int(c*factor+8) for c in rgb)+(255,))
        im.paste(gradient, (0,0), mask)
    if kind == 'logo':
        box((7,15,43,57), '#087deb', 7)
        box((14,10,50,53), '#22b6ff', 7)
        shadow = im.filter(ImageFilter.GaussianBlur(4*s))
        im = Image.alpha_composite(shadow, im)
        d = ImageDraw.Draw(im)
        box((22,5,55,47), '#f0f7ff', 5)
        for y,end in ((17,46),(25,46),(33,41)):
            line([(29,y),(end,y+2)], '#1188f5', 3)
    elif kind == 'chevron_down':
        line([(15,24),(32,41),(49,24)], width=5)
    elif kind == 'summary':
        d.polygon([(12*s,30*s),(32*s,12*s),(52*s,30*s)], fill=color)
        box((19,28,45,51), color, 3)
        box((28,37,36,52), '#0b2540', 2)
    elif kind == 'document':
        box((18,12,46,52), color, 4)
        for y,end in ((24,38),(32,38),(40,33)):
            line([(25,y),(end,y)], '#0b2540', 3)
    elif kind == 'users':
        circle((16,13,32,29), fill=color)
        circle((37,17,49,29), fill=color)
        box((12,33,36,49), color, 8)
        box((39,33,54,48), color, 6)
    elif kind == 'active':
        circle((12,12,52,52), fill=color)
        line([(22,32),(29,39),(43,24)], '#072536', 4)
    elif kind == 'disabled':
        line([(22,24),(22,39),(44,39),(44,23),(38,17),(27,17)], width=3)
        line([(28,45),(36,45)], width=3)
        line([(14,13),(51,51)], width=4)
    elif kind == 'clock':
        circle((12,12,52,52), outline=color)
        line([(32,20),(32,32),(42,38)], width=3)
    elif kind == 'refresh':
        d.arc((13*s,13*s,51*s,51*s), 40, 315, fill=color, width=3*s)
        d.polygon([(47*s,12*s),(52*s,27*s),(37*s,24*s)], fill=color)
    elif kind == 'settings':
        for a in range(0,360,45):
            angle=math.radians(a)
            line([(32+18*math.cos(angle),32+18*math.sin(angle)),
                  (32+25*math.cos(angle),32+25*math.sin(angle))], width=7)
        circle((12,12,52,52), fill=color)
        circle((24,24,40,40), fill='#0c1f33')
    elif kind == 'trash':
        line([(20,22),(22,49),(43,49),(45,22)], width=3)
        line([(15,19),(49,19)], width=3)
        line([(25,18),(25,13),(39,13),(39,18)], width=3)
        line([(29,28),(29,42)], width=2)
        line([(36,28),(36,42)], width=2)
    elif kind == 'plus':
        line([(32,15),(32,49)], width=4)
        line([(15,32),(49,32)], width=4)
    return im


@lru_cache(maxsize=64)
def icon(kind, size=28, color='#369eff', tile=False):
    image = artwork(kind, color, tile)
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size,size))
