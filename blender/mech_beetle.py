# -*- coding: utf-8 -*-
"""
Шагающий мех-жук с городком на спине — процедурная модель для Blender.

Как запустить:
  1. Откройте Blender (3.6 и новее, проверено на 4.2).
  2. Вкладка «Scripting» → «Open» → выберите этот файл
     (или создайте новый Text и вставьте содержимое).
  3. Нажмите «Run Script» (Alt+P).

Скрипт строит робота, землю, солнце и камеру; вьюпорт переключается
в вид из камеры. F12 — рендер.

Масштаб реальный, в метрах: корпус ~36 м, человечки на палубе 1.75 м.
Панцири крепятся к пустышкам MB_ShellPivot_R / MB_ShellPivot_L:
поверните пустышку по оси Y, чтобы открыть или закрыть панцирь.
Весь робот висит на пустышке MB_Root — двигайте и масштабируйте её.
"""

import math

import bpy
from mathutils import Euler, Vector

# ============================================================== настройки
CLEAR_SCENE = True      # удалить ВСЕ объекты сцены перед сборкой
SHELL_OPEN_R = 40.0     # раскрытие правого по ходу робота панциря (в кадре слева), градусы
SHELL_OPEN_L = 10.0     # раскрытие левого панциря (в кадре справа), градусы
BUILD_TOWN = True       # домики, ящики и перила на палубе
BUILD_PEOPLE = True     # человечки
SETUP_SCENE = True      # земля, солнце, камера, фон, настройки рендера
RENDER_ENGINE = 'EEVEE'  # 'EEVEE' (быстро) или 'CYCLES' (красивее, медленнее)

DECK_Z = 14.3           # высота верха палубы
SHELL_PIVOT = (5.4, -4.0, 17.0)  # (|x|, y, z) петли панциря: передний край верхней кромки

UP = Vector((0.0, 0.0, 1.0))


def V(x, y, z):
    return Vector((x, y, z))


def frange(a, b, step):
    out = []
    x = a
    while x < b - 1e-9:
        out.append(x)
        x += step
    return out


def frame(axis, hint=UP):
    """Правая тройка (side, up, axis): axis — вдоль детали, up — ближе всего к hint."""
    a = Vector(axis).normalized()
    h = Vector(hint).normalized()
    if abs(a.dot(h)) > 0.999:
        h = V(1, 0, 0) if abs(a.x) < 0.9 else V(0, 1, 0)
    side = h.cross(a).normalized()
    return side, a.cross(side), a


def newell(pts):
    n = Vector()
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        n.x += (p.y - q.y) * (p.z + q.z)
        n.y += (p.z - q.z) * (p.x + q.x)
        n.z += (p.x - q.x) * (p.y + q.y)
    return n


# ============================================================== геометрия
class Part:
    """Копилка геометрии: много примитивов → один меш со слотами материалов."""

    def __init__(self, name):
        self.name = name
        self.verts = []
        self.faces = []
        self.face_mat = []
        self.face_smooth = []
        self.face_uv = []
        self.mats = []

    def slot(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def add(self, verts, faces, mat, smooth=False, uvs=None):
        base = len(self.verts)
        self.verts.extend(Vector(p) for p in verts)
        mi = self.slot(mat)
        for i, f in enumerate(faces):
            self.faces.append([base + j for j in f])
            self.face_mat.append(mi)
            self.face_smooth.append(smooth)
            self.face_uv.append(uvs[i] if uvs else None)

    def mirror_x(self):
        for p in self.verts:
            p.x = -p.x
        self.faces = [f[::-1] for f in self.faces]
        self.face_uv = [u[::-1] if u else None for u in self.face_uv]

    def build(self, coll, parent=None, bevel=0.0):
        me = bpy.data.meshes.new(self.name)
        me.from_pydata([p[:] for p in self.verts], [], self.faces)
        for m in self.mats:
            me.materials.append(m)
        me.polygons.foreach_set('material_index', self.face_mat)
        me.polygons.foreach_set('use_smooth', self.face_smooth)
        if any(self.face_uv):
            layer = me.uv_layers.new(name='UVMap')
            flat = []
            for f, u in zip(self.faces, self.face_uv):
                for k in range(len(f)):
                    flat.extend(u[k] if u else (0.0, 0.0))
            layer.data.foreach_set('uv', flat)
        me.validate(clean_customdata=False)
        me.update()
        ob = bpy.data.objects.new(self.name, me)
        coll.objects.link(ob)
        ob.parent = parent
        if bevel > 0:
            md = ob.modifiers.new('Bevel', 'BEVEL')
            md.width = bevel
            md.segments = 2
            md.limit_method = 'ANGLE'
            md.angle_limit = math.radians(35)
        return ob


def cap(part, mat, ring, outward):
    pts = ring if newell(ring).dot(outward) >= 0 else ring[::-1]
    part.add(pts, [list(range(len(pts)))], mat)


def loft(part, mat, rings, caps=True, smooth=False):
    """Труба через замкнутые сечения; нормали автоматически наружу."""
    rings = [[Vector(p) for p in r] for r in rings]
    n = len(rings[0])
    score = 0.0
    for i in range(len(rings) - 1):
        c = sum(rings[i], Vector()) / n
        for j in range(n):
            a, b, d = rings[i][j], rings[i][(j + 1) % n], rings[i + 1][j]
            score += (b - a).cross(d - a).dot((a + b) / 2 - c)
    if score < 0:
        rings = [r[::-1] for r in rings]
    faces = []
    for i in range(len(rings) - 1):
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((i * n + j, i * n + j2, (i + 1) * n + j2, (i + 1) * n + j))
    part.add([p for r in rings for p in r], faces, mat, smooth)
    if caps:
        axis = sum(rings[-1], Vector()) - sum(rings[0], Vector())
        cap(part, mat, rings[0], -axis)
        cap(part, mat, rings[-1], axis)


def rect_ring(c, side, up, w, h):
    return [c - side * w / 2 - up * h / 2, c + side * w / 2 - up * h / 2,
            c + side * w / 2 + up * h / 2, c - side * w / 2 + up * h / 2]


def circle_ring(c, side, up, r, n):
    return [c + side * (r * math.cos(2 * math.pi * i / n)) + up * (r * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def box(part, mat, c, size, rot=(0, 0, 0), axes=None):
    """Параллелепипед; rot — углы XYZ в градусах, либо готовые оси axes=(X, Y, Z)."""
    if axes is None:
        m = Euler([math.radians(a) for a in rot], 'XYZ').to_matrix()
        axes = (m.col[0], m.col[1], m.col[2])
    X, Y, Z = axes
    c = Vector(c)
    sx, sy, sz = size
    loft(part, mat, [rect_ring(c - Z * sz / 2, X, Y, sx, sy), rect_ring(c + Z * sz / 2, X, Y, sx, sy)])


def beam(part, mat, p1, p2, w, h, w2=None, h2=None, hint=UP):
    """Брус (можно сужающийся) от точки p1 до p2."""
    p1, p2 = Vector(p1), Vector(p2)
    side, up, _ = frame(p2 - p1, hint)
    loft(part, mat, [rect_ring(p1, side, up, w, h),
                     rect_ring(p2, side, up, w if w2 is None else w2, h if h2 is None else h2)])


def cyl(part, mat, c, axis, r, length, segs=24, r2=None, smooth=True):
    side, up, ax = frame(axis)
    c = Vector(c)
    loft(part, mat, [circle_ring(c - ax * length / 2, side, up, r, segs),
                     circle_ring(c + ax * length / 2, side, up, r if r2 is None else r2, segs)],
         smooth=smooth)


def rod(part, mat, p1, p2, r, segs=12):
    p1, p2 = Vector(p1), Vector(p2)
    cyl(part, mat, (p1 + p2) / 2, p2 - p1, r, (p2 - p1).length, segs)


def add_outward(part, mat, verts, faces, center, smooth=True, uvs=None):
    """Добавить сетку, развернув каждую грань «от центра» (для выпуклых форм)."""
    center = Vector(center)
    fixed, fixed_uv = [], []
    for i, f in enumerate(faces):
        pts = [verts[k] for k in f]
        fc = sum(pts, Vector()) / len(pts)
        flip = newell(pts).dot(fc - center) < 0
        fixed.append(f[::-1] if flip else f)
        if uvs:
            fixed_uv.append(uvs[i][::-1] if flip else uvs[i])
    part.add(verts, fixed, mat, smooth, fixed_uv or None)


def ellipsoid(part, mat, c, radii, segs=12, rings=8):
    c = Vector(c)
    rx, ry, rz = radii
    verts = [c + V(0, 0, -rz)]
    for k in range(1, rings):
        th = -math.pi / 2 + math.pi * k / rings
        for j in range(segs):
            ph = 2 * math.pi * j / segs
            verts.append(c + V(rx * math.cos(th) * math.cos(ph), ry * math.cos(th) * math.sin(ph), rz * math.sin(th)))
    verts.append(c + V(0, 0, rz))
    top = len(verts) - 1
    faces = []
    for j in range(segs):
        j2 = (j + 1) % segs
        faces.append((0, 1 + j2, 1 + j))
        faces.append((top, 1 + (rings - 2) * segs + j, 1 + (rings - 2) * segs + j2))
    for k in range(rings - 2):
        for j in range(segs):
            j2 = (j + 1) % segs
            a, b = 1 + k * segs, 1 + (k + 1) * segs
            faces.append((a + j, a + j2, b + j2, b + j))
    add_outward(part, mat, verts, faces, c)


def bolts(part, mat, c, axis, ring_r, n, br=0.09, h=0.14):
    side, up, ax = frame(axis)
    for i in range(n):
        ang = 2 * math.pi * i / n
        p = Vector(c) + (side * math.cos(ang) + up * math.sin(ang)) * ring_r
        cyl(part, mat, p, ax, br, h, segs=6, smooth=False)


def gear(part, mat, c, axis, r, thick, teeth=14):
    side, up, ax = frame(axis)
    c = Vector(c)
    cyl(part, mat, c, ax, r * 0.84, thick, segs=teeth * 2)
    cyl(part, mat, c, ax, r * 0.35, thick * 1.6, segs=12)
    for i in range(teeth):
        ang = 2 * math.pi * (i + 0.5) / teeth
        radial = side * math.cos(ang) + up * math.sin(ang)
        box(part, mat, c + radial * r * 0.9, (r * 0.22, r * 0.18, thick * 0.9),
            axes=(radial, ax.cross(radial), ax))


def piston(part, M, p1, p2, r=0.3):
    """Гидроцилиндр: корпус, хромированный шток и проушины."""
    p1, p2 = Vector(p1), Vector(p2)
    d = p2 - p1
    rod(part, M['dark'], p1, p1 + d * 0.58, r, 14)
    cyl(part, M['dark'], p1 + d * 0.58, d, r * 1.2, r * 0.6, 14)
    rod(part, M['steel'], p1 + d * 0.5, p2, r * 0.5, 12)
    side, _, _ = frame(d)
    for p in (p1, p2):
        cyl(part, M['dark'], p, side, r * 1.25, r * 1.7, 12)


# ============================================================== материалы
def _new_mat(name, viewport_rgb):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except AttributeError:
        pass
    m.diffuse_color = (*viewport_rgb, 1.0)
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    return m, nt, out


def _bsdf(nt, out, color, rough=0.5, metal=0.0):
    b = nt.nodes.new('ShaderNodeBsdfPrincipled')
    b.inputs['Base Color'].default_value = (*color, 1.0)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    nt.links.new(b.outputs[0], out.inputs['Surface'])
    return b


def _ramp(nt, stops):
    r = nt.nodes.new('ShaderNodeValToRGB')
    el = r.color_ramp.elements
    while len(el) < len(stops):
        el.new(0.5)
    for e, (pos, col) in zip(el, stops):
        e.position = pos
        e.color = (*col, 1.0) if len(col) == 3 else (col[0], col[0], col[0], 1.0)
    return r


def _noise(nt, vec, scale, detail, rough):
    n = nt.nodes.new('ShaderNodeTexNoise')
    n.inputs['Scale'].default_value = scale
    n.inputs['Detail'].default_value = detail
    n.inputs['Roughness'].default_value = rough
    nt.links.new(vec, n.inputs['Vector'])
    return n


def mat_paint(name, panels=False):
    """Жёлтая краска с серыми проплешинами и ржавчиной; panels=True — швы панелей по UV."""
    m, nt, out = _new_mat(name, (0.62, 0.36, 0.06))
    N, L = nt.nodes, nt.links
    b = _bsdf(nt, out, (0.62, 0.36, 0.06), 0.55, 0.1)
    tc = N.new('ShaderNodeTexCoord')
    big = _noise(nt, tc.outputs['Object'], 0.22, 6.0, 0.62)
    fine = _noise(nt, tc.outputs['Object'], 2.5, 10.0, 0.7)
    m1 = N.new('ShaderNodeMath')
    m1.operation = 'MULTIPLY'
    L.new(big.outputs['Fac'], m1.inputs[0])
    m1.inputs[1].default_value = 0.7
    m2 = N.new('ShaderNodeMath')
    m2.operation = 'MULTIPLY_ADD'
    L.new(fine.outputs['Fac'], m2.inputs[0])
    m2.inputs[1].default_value = 0.3
    L.new(m1.outputs[0], m2.inputs[2])
    col = _ramp(nt, [(0.30, (0.66, 0.38, 0.05)), (0.50, (0.52, 0.27, 0.025)),
                     (0.565, (0.22, 0.10, 0.025)), (0.585, (0.26, 0.25, 0.22)), (0.80, (0.16, 0.15, 0.13))])
    L.new(m2.outputs[0], col.inputs['Fac'])
    rough = _ramp(nt, [(0.5, (0.45,)), (0.6, (0.75,))])
    L.new(m2.outputs[0], rough.inputs['Fac'])
    L.new(rough.outputs['Color'], b.inputs['Roughness'])
    bump = N.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = 0.25
    bump.inputs['Distance'].default_value = 0.02
    L.new(fine.outputs['Fac'], bump.inputs['Height'])
    L.new(bump.outputs['Normal'], b.inputs['Normal'])
    if not panels:
        L.new(col.outputs['Color'], b.inputs['Base Color'])
        return m
    # швы панелей: текстура «кирпич» по UV (белые панели, чёрные швы)
    brick = N.new('ShaderNodeTexBrick')
    brick.offset = 0.5
    brick.inputs['Color1'].default_value = (1, 1, 1, 1)
    brick.inputs['Color2'].default_value = (1, 1, 1, 1)
    brick.inputs['Mortar'].default_value = (0, 0, 0, 1)
    brick.inputs['Scale'].default_value = 1.0
    brick.inputs['Mortar Size'].default_value = 0.05
    brick.inputs['Brick Width'].default_value = 3.2
    brick.inputs['Row Height'].default_value = 2.0
    L.new(tc.outputs['UV'], brick.inputs['Vector'])
    seam = _ramp(nt, [(0.0, (0.25,)), (1.0, (1.0,))])
    L.new(brick.outputs['Color'], seam.inputs['Fac'])
    mul = N.new('ShaderNodeVectorMath')
    mul.operation = 'MULTIPLY'
    L.new(col.outputs['Color'], mul.inputs[0])
    L.new(seam.outputs['Color'], mul.inputs[1])
    L.new(mul.outputs['Vector'], b.inputs['Base Color'])
    bump2 = N.new('ShaderNodeBump')
    bump2.inputs['Strength'].default_value = 0.6
    bump2.inputs['Distance'].default_value = 0.05
    L.new(brick.outputs['Color'], bump2.inputs['Height'])
    L.new(bump2.outputs['Normal'], bump.inputs['Normal'])
    return m


def mat_metal(name, color, rough=0.45, metal=0.8):
    m, nt, out = _new_mat(name, color)
    b = _bsdf(nt, out, color, rough, metal)
    tc = nt.nodes.new('ShaderNodeTexCoord')
    n = _noise(nt, tc.outputs['Object'], 1.2, 8.0, 0.6)
    r = _ramp(nt, [(0.35, tuple(c * 0.6 for c in color)), (0.7, tuple(c * 1.25 for c in color))])
    nt.links.new(n.outputs['Fac'], r.inputs['Fac'])
    nt.links.new(r.outputs['Color'], b.inputs['Base Color'])
    return m


def mat_plain(name, color, rough=0.7, metal=0.0):
    m, nt, out = _new_mat(name, color)
    _bsdf(nt, out, color, rough, metal)
    return m


def mat_emit(name, color, strength):
    m, nt, out = _new_mat(name, color)
    e = nt.nodes.new('ShaderNodeEmission')
    e.inputs['Color'].default_value = (*color, 1.0)
    e.inputs['Strength'].default_value = strength
    nt.links.new(e.outputs[0], out.inputs['Surface'])
    return m


def mat_deck(name):
    """Бетонные плиты палубы."""
    m, nt, out = _new_mat(name, (0.40, 0.38, 0.34))
    N, L = nt.nodes, nt.links
    b = _bsdf(nt, out, (0.4, 0.38, 0.34), 0.85)
    tc = N.new('ShaderNodeTexCoord')
    br = N.new('ShaderNodeTexBrick')
    br.offset = 0.0
    br.inputs['Color1'].default_value = (0.42, 0.40, 0.36, 1)
    br.inputs['Color2'].default_value = (0.34, 0.32, 0.29, 1)
    br.inputs['Mortar'].default_value = (0.12, 0.11, 0.10, 1)
    br.inputs['Scale'].default_value = 1.0
    br.inputs['Mortar Size'].default_value = 0.03
    br.inputs['Brick Width'].default_value = 1.9
    br.inputs['Row Height'].default_value = 1.9
    L.new(tc.outputs['Object'], br.inputs['Vector'])
    n = _noise(nt, tc.outputs['Object'], 0.6, 6.0, 0.6)
    dirt = _ramp(nt, [(0.4, (0.75,)), (0.65, (1.05,))])
    L.new(n.outputs['Fac'], dirt.inputs['Fac'])
    mul = N.new('ShaderNodeVectorMath')
    mul.operation = 'MULTIPLY'
    L.new(br.outputs['Color'], mul.inputs[0])
    L.new(dirt.outputs['Color'], mul.inputs[1])
    L.new(mul.outputs['Vector'], b.inputs['Base Color'])
    return m


def make_materials():
    return {
        'paint': mat_paint('MB_Paint'),
        'shell': mat_paint('MB_ShellPaint', panels=True),
        'shell_in': mat_metal('MB_ShellInner', (0.10, 0.085, 0.07), 0.6, 0.4),
        'dark': mat_metal('MB_DarkMetal', (0.07, 0.07, 0.075), 0.42, 0.85),
        'steel': mat_plain('MB_Steel', (0.65, 0.65, 0.66), 0.22, 1.0),
        'deck': mat_deck('MB_Deck'),
        'brick': mat_metal('MB_Brick', (0.36, 0.08, 0.05), 0.85, 0.0),
        'green': mat_metal('MB_GreenPaint', (0.24, 0.32, 0.24), 0.75, 0.0),
        'roof': mat_plain('MB_Roof', (0.12, 0.12, 0.12), 0.8),
        'window': mat_plain('MB_Window', (0.03, 0.035, 0.04), 0.15),
        'person': mat_plain('MB_Person', (0.025, 0.025, 0.03), 0.8),
        'lamp': mat_emit('MB_Lamp', (1.0, 0.55, 0.18), 12.0),
        'eye': mat_emit('MB_Eye', (1.0, 0.62, 0.22), 14.0),
        'ground': mat_plain('MB_Ground', (0.75, 0.67, 0.53), 1.0),
    }


# ============================================================== корпус
HULL_PROFILE = [(4.3, 14.0), (5.1, 13.2), (5.4, 11.0), (4.8, 9.1), (3.1, 8.1),
                (-3.1, 8.1), (-4.8, 9.1), (-5.4, 11.0), (-5.1, 13.2), (-4.3, 14.0)]


def hull_ring(y, sx=1.0, sz=1.0, dz=0.0, zc=11.0):
    return [V(x * sx, y, zc + (z - zc) * sz + dz) for x, z in HULL_PROFILE]


def build_hull(M):
    P = Part('MB_Hull')
    paint, dark, steel, lamp = M['paint'], M['dark'], M['steel'], M['lamp']

    # основной корпус и сужающаяся корма
    loft(P, paint, [hull_ring(-11.5, 0.97), hull_ring(-4), hull_ring(11), hull_ring(14.8, 0.93, 0.95),
                    hull_ring(16.9, 0.72, 0.8), hull_ring(17.8, 0.45, 0.6)])
    # голова
    loft(P, paint, [hull_ring(-11.0, 0.96), hull_ring(-14.2, 0.86, 0.88, -0.1),
                    hull_ring(-17.2, 0.7, 0.72, -0.35), hull_ring(-18.4, 0.62, 0.62, -0.5)])
    fy = -18.4
    box(P, dark, (0, fy - 0.05, 11.65), (3.8, 0.3, 1.1))                  # визор
    for s in (-1, 1):
        box(P, M['eye'], (s * 0.95, fy - 0.22, 11.65), (1.35, 0.12, 0.6))  # глаза
    box(P, paint, (0, fy - 0.45, 12.45), (4.3, 1.5, 0.55), rot=(12, 0, 0))  # бровь
    box(P, dark, (0, fy - 0.35, 9.4), (1.8, 1.3, 3.6))                   # решётка «носа»
    for k in range(5):
        box(P, steel, (-0.64 + k * 0.32, fy - 1.03, 9.4), (0.12, 0.1, 3.2))
    for s in (-1, 1):
        box(P, paint, (s * 1.8, fy - 0.15, 9.3), (1.3, 1.7, 3.0), rot=(0, s * 8, -s * 14))  # жвалы
        box(P, paint, (s * 3.55, -15.3, 11.1), (0.6, 5.2, 3.0), rot=(0, -s * 10, s * 8))   # щёки
    box(P, dark, (0, -16.0, 7.9), (3.4, 4.0, 1.2))                       # подбородок
    box(P, paint, (0, -14.4, 13.75), (5.8, 4.6, 0.55))                   # пластины лба
    box(P, paint, (0, -16.9, 13.15), (4.7, 2.6, 0.5), rot=(14, 0, 0))

    for s in (-1, 1):
        # парапет вдоль краёв палубы
        for y in frange(-10.6, 14.6, 2.75):
            box(P, paint, (s * 4.55, y + 1.375, 14.5), (1.1, 2.6, 0.9))
        # бортовая броня, вентиляция, огоньки
        for i, y0 in enumerate(frange(-10.0, 14.0, 3.5)):
            yc = y0 + 1.75
            box(P, paint, (s * 5.3, yc, 12.2), (0.55, 3.3, 2.0), rot=(0, -s * 8, 0))
            box(P, paint, (s * 5.15, yc, 10.1), (0.55, 3.3, 2.0), rot=(0, s * 16, 0))
            if i % 2 == 0:
                box(P, dark, (s * 5.58, yc, 12.2), (0.12, 1.8, 0.85), rot=(0, -s * 8, 0))
                for k in range(4):
                    box(P, paint, (s * 5.63, yc, 11.92 + k * 0.19), (0.12, 1.7, 0.07), rot=(0, -s * 8, 0))
            box(P, lamp, (s * 5.12, yc - 1.1, 13.55), (0.12, 0.55, 0.18))
        # опора петли панциря («плечо»)
        px, py, pz = SHELL_PIVOT
        beam(P, paint, V(s * 4.6, py, 14.4), V(s * px, py, pz - 1.0), 2.4, 3.2, 1.8, 2.4)
        for dy in (-1.0, 1.0):
            beam(P, dark, V(s * 4.4, py + dy * 2.2, 14.5), V(s * px, py + dy * 0.9, pz), 0.6, 0.6)
        piston(P, M, V(s * 4.5, py + 3.2, 14.6), V(s * (px + 0.2), py + 1.2, pz - 1.5), 0.25)

    # брюхо: валы, шестерни, гидравлика
    box(P, dark, (0, 2.5, 7.7), (5.2, 25.0, 1.0))
    for y in (-8.5, -4.0, 0.5, 5.0, 9.5, 13.5):
        cyl(P, dark, (0, y, 7.45), V(1, 0, 0), 1.05, 7.2)
        for s in (-1, 1):
            cyl(P, paint, (s * 3.75, y, 7.45), V(1, 0, 0), 0.75, 0.35)
            bolts(P, steel, (s * 3.95, y, 7.45), V(1, 0, 0), 0.5, 6)
    for s in (-1, 1):
        for y in (-6.3, -1.8, 2.7, 7.2, 11.5):
            piston(P, M, V(s * 2.2, y - 1.2, 6.8), V(s * 2.2, y + 1.2, 6.8), 0.28)
    # корма
    for s in (-1, 1):
        cyl(P, dark, (s * 1.7, 17.7, 10.8), V(0, 1, 0), 0.8, 1.6)
        cyl(P, lamp, (s * 1.7, 18.52, 10.8), V(0, 1, 0), 0.45, 0.05)
    box(P, paint, (0, 17.6, 12.5), (4.6, 1.0, 1.0), rot=(-20, 0, 0))
    return P


def build_deck(M):
    P = Part('MB_Deck')
    box(P, M['deck'], (0, 2.2, DECK_Z - 0.175), (7.8, 26.4, 0.35))
    box(P, M['paint'], (0, -11.0, DECK_Z + 0.45), (7.9, 1.0, 0.9))  # передний фальшборт
    return P


# ============================================================== ноги
def build_leg(P, M, s, hip, knee, ankle, foot):
    paint, dark, steel = M['paint'], M['dark'], M['steel']
    hip, knee, ankle, foot = Vector(hip), Vector(knee), Vector(ankle), Vector(foot)
    d = foot - hip
    d.z = 0
    d.normalize()
    jax = UP.cross(d).normalized()   # ось шарниров колена и голеностопа

    # тазобедренный узел
    gear(P, dark, V(s * 5.0, hip.y, hip.z + 0.2), V(1, 0, 0), 1.6, 0.45, 16)
    beam(P, dark, V(s * 4.2, hip.y, hip.z + 0.2), hip, 1.6, 1.8)
    cyl(P, dark, hip, jax, 1.4, 2.4)
    for sg in (-1, 1):
        cc = hip + jax * sg * 1.25
        cyl(P, paint, cc, jax, 1.0, 0.3)
        bolts(P, steel, cc + jax * sg * 0.15, jax, 0.72, 8)

    # бедро: каркас + броневые плиты
    tside, tup, _ = frame(knee - hip)
    beam(P, dark, hip, knee, 1.2, 1.3)
    for a0, a1 in ((0.12, 0.52), (0.55, 0.9)):
        beam(P, paint, hip.lerp(knee, a0) + tup * 0.55, hip.lerp(knee, a1) + tup * 0.55, 2.0, 1.0, 1.85, 0.95)
    for sg in (-1, 1):
        beam(P, paint, hip.lerp(knee, 0.2) + tside * sg * 0.72, hip.lerp(knee, 0.85) + tside * sg * 0.72,
             0.18, 1.1)
    for sg in (-1, 1):
        piston(P, M, V(s * 3.4, hip.y + sg * 0.7, 7.3), hip.lerp(knee, 0.62) - tup * 0.6 + jax * sg * 0.45, 0.26)

    # колено
    cyl(P, dark, knee, jax, 1.25, 2.6)
    for sg in (-1, 1):
        cc = knee + jax * sg * 1.35
        cyl(P, paint, cc, jax, 0.85, 0.3)
        bolts(P, steel, cc + jax * sg * 0.15, jax, 0.6, 6)

    # голень: продолжается выше колена, три броневых сегмента
    sdir = (ankle - knee).normalized()
    sside, sup, _ = frame(ankle - knee, d)
    top = knee - sdir * 1.3
    beam(P, dark, top, ankle, 1.5, 1.7, 1.2, 1.3, hint=d)
    for a0, a1 in ((0.0, 0.33), (0.36, 0.68), (0.71, 0.9)):
        w0, w1 = 1.85 - 0.4 * a0, 1.85 - 0.4 * a1
        h0, h1 = 2.2 - 0.6 * a0, 2.2 - 0.6 * a1
        beam(P, paint, top.lerp(ankle, a0) + sup * 0.2, top.lerp(ankle, a1) + sup * 0.2, w0, h0, w1, h1, hint=d)
    # решётки на внешней стороне голени
    for a in (0.18, 0.5):
        c = top.lerp(ankle, a) + sup * (1.45 - 0.35 * a)
        box(P, dark, c, (1.0, 0.12, 1.3), axes=(sside, sup, sdir))
    # гидроцилиндр вдоль внутренней стороны
    piston(P, M, top.lerp(ankle, 0.12) - sup * 1.35, ankle - sup * 0.8 - sdir * 0.4, 0.3)

    # голеностоп
    cyl(P, dark, ankle, jax, 0.95, 2.0)
    for sg in (-1, 1):
        cyl(P, paint, ankle + jax * sg * 1.05, jax, 0.65, 0.25)
    hub = foot + V(0, 0, 1.1)
    beam(P, dark, ankle, hub, 1.1, 1.1, hint=d)

    # ступня: ступица и пять когтей
    cyl(P, dark, hub, UP, 1.15, 1.3, segs=8, smooth=False)
    cyl(P, paint, hub + V(0, 0, 0.75), UP, 0.95, 0.25, segs=8, smooth=False)
    base = math.atan2(d.y, d.x)
    for k in range(5):
        ang = base + math.radians(36 + 72 * k)
        rd = V(math.cos(ang), math.sin(ang), 0)
        side = UP.cross(rd)
        p0 = hub + rd * 0.6
        knuckle = foot + rd * 1.6 + V(0, 0, 1.15)
        tip = foot + rd * 2.55 + V(0, 0, 0.35)
        beam(P, dark, p0, knuckle, 0.75, 0.8)
        cyl(P, dark, knuckle, side, 0.42, 0.95, 12)
        beam(P, paint, knuckle + V(0, 0, 0.15), tip + V(0, 0, 0.2), 0.85, 0.7, 0.8, 0.55)
        box(P, dark, tip, (1.1, 0.95, 0.7), axes=(rd, side, UP))
        box(P, paint, tip + rd * 0.35 + V(0, 0, 0.12), (0.5, 0.9, 0.55), axes=(rd, side, UP))


# (y бедра, |x| колена, y колена, z колена, |x| стопы, y стопы)
LEGS = [
    (-7.5, 13.0, -12.0, 10.5, 17.0, -17.0),
    (2.0, 15.0, 2.0, 10.0, 19.5, 2.5),
    (11.0, 13.0, 15.5, 10.5, 17.0, 20.5),
]


def build_legs(M, coll, root):
    for s, side_name in ((1, 'L'), (-1, 'R')):
        for i, (yh, kx, ky, kz, fx, fy) in enumerate(LEGS):
            P = Part('MB_Leg_%s%d' % (side_name, i + 1))
            foot = V(s * fx, fy, 0)
            build_leg(P, M, s, V(s * 5.0, yh, 9.0), V(s * kx, ky, kz), foot + V(-s * 0.3, 0, 3.4), foot)
            P.build(coll, root, bevel=0.06)


# ============================================================== панцири
SHELL_R = (6.5, 11.0, 7.5)   # полуоси «яйца»: наружу, вдоль, вверх
SHELL_EGG = 0.18            # насколько задний конец толще переднего
SHELL_A_MIN = -0.5          # нижняя кромка (рад от «экватора»): снизу панцирь открыт для ног
SHELL_HINGE_T = 0.2 * math.pi  # где на верхней кромке стоит петля (0 — нос, π — хвост)


def _shell_raw(t, a, inset):
    rx, ry, rz = SHELL_R
    g = math.sin(t) * (1.0 - SHELL_EGG * math.cos(t))
    return V((rx - inset) * g * math.cos(a), -(ry - inset) * math.cos(t), (rz - inset) * g * math.sin(a))


def shell_pt(t, a, inset=0.0):
    """t ∈ [0, π] — от носа к хвосту, a — от нижней кромки (SHELL_A_MIN) до верхней (π/2).
    Начало координат — на петле, у переднего конца верхней кромки."""
    return _shell_raw(t, a, inset) - _shell_raw(SHELL_HINGE_T, math.pi / 2, 0.0)


def shell_frame_at(t, a, inset=0.0):
    """Точка на панцире и оси (вдоль, поперёк, нормаль наружу)."""
    e = 1e-3
    p = shell_pt(t, a, inset)
    tt = (shell_pt(t + e, a, inset) - shell_pt(t - e, a, inset)).normalized()
    ta = shell_pt(t, a + e, inset) - shell_pt(t, a - e, inset)
    n = tt.cross(ta).normalized()
    return p, (tt, n.cross(tt), n)


def shell_sweep(part, mat, pts, inward, w, h):
    rings = []
    for k, p in enumerate(pts):
        tan = pts[min(k + 1, len(pts) - 1)] - pts[max(k - 1, 0)]
        side, up, _ = frame(tan, inward[k])
        rings.append(rect_ring(p, side, up, w, h))
    loft(part, mat, rings)


def build_shell(M, s, open_deg, coll, root):
    name = 'L' if s > 0 else 'R'
    px, py, pz = SHELL_PIVOT
    pivot = bpy.data.objects.new('MB_ShellPivot_' + name, None)
    pivot.empty_display_type = 'ARROWS'
    pivot.empty_display_size = 3
    coll.objects.link(pivot)
    pivot.parent = root
    pivot.location = (s * px, py, pz)
    pivot.rotation_mode = 'YXZ'
    # как у жука: панцирь откидывается наружу и задирает задний конец
    pivot.rotation_euler = (math.radians(3 + open_deg * 0.45), math.radians(-s * open_deg), math.radians(-s * 6))

    # скорлупа: верхне-внешняя часть половинки «яйца»
    rx, ry, rz = SHELL_R
    nt_, na = 48, 24
    a_max = math.pi / 2
    ts = [math.pi * i / nt_ for i in range(nt_ + 1)]
    as_ = [SHELL_A_MIN + (a_max - SHELL_A_MIN) * j / na for j in range(na + 1)]
    uv = lambda i, j: (ts[i] * ry * 0.9, (as_[j] - SHELL_A_MIN) * (rx + rz) * 0.5)
    verts, faces, uvs = [], [], []
    idx = {}
    for i in range(nt_ + 1):
        for j in range(na + 1):
            if i in (0, nt_) and j > 0:
                idx[i, j] = idx[i, 0]  # полюс — одна вершина
                continue
            idx[i, j] = len(verts)
            verts.append(shell_pt(ts[i], as_[j]))
    for i in range(nt_):
        for j in range(na):
            f, fuv = [], []
            for key in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)):
                if idx[key] not in f:
                    f.append(idx[key])
                    fuv.append(uv(*key))
            faces.append(f)
            uvs.append(fuv)
    S = Part('MB_Shell_' + name)
    S.slot(M['shell'])
    S.slot(M['shell_in'])
    add_outward(S, M['shell'], verts, faces, -_shell_raw(SHELL_HINGE_T, math.pi / 2, 0.0), smooth=True, uvs=uvs)

    # изнутри: рёбра жёсткости, петля, подкосы, огни; снаружи — решётки
    F = Part('MB_ShellFrame_' + name)
    dark, paint, lamp = M['dark'], M['paint'], M['lamp']
    for t in [math.pi * k for k in (0.2, 0.32, 0.44, 0.56, 0.68, 0.8)]:
        pts, inward = [], []
        for j in range(21):
            a = SHELL_A_MIN + 0.06 + (a_max - SHELL_A_MIN - 0.12) * j / 20
            p, (_, _, n) = shell_frame_at(t, a, 0.55)
            pts.append(p)
            inward.append(-n)
        shell_sweep(F, dark, pts, inward, 0.35, 0.5)
    for a in (-0.15, 0.35, 0.85, 1.3):
        pts, inward = [], []
        for k in range(25):
            p, (_, _, n) = shell_frame_at(math.pi * (0.12 + 0.76 * k / 24), a, 0.6)
            pts.append(p)
            inward.append(-n)
        shell_sweep(F, dark, pts, inward, 0.3, 0.4)
    # петля и силовая балка вдоль верхней кромки
    cyl(F, dark, (0, 0, 0), V(0, 1, 0), 1.0, 3.2)
    for y in (-1.9, 1.9):
        cyl(F, paint, (0, y, 0), V(0, 1, 0), 1.15, 0.6)
    spine = [shell_frame_at(math.pi * (0.2 + 0.6 * k / 16), math.pi / 2 - 0.25, 0.5) for k in range(17)]
    shell_sweep(F, dark, [p for p, _ in spine], [-f[2] for _, f in spine], 0.7, 0.7)
    beam(F, dark, V(0, 0.5, 0), spine[3][0], 0.8, 0.8)
    for t in (0.4 * math.pi, 0.62 * math.pi):
        p, _ = shell_frame_at(t, math.pi / 2 - 0.25, 0.9)
        q, _ = shell_frame_at(t, -0.1, 0.6)
        piston(F, M, p, q, 0.22)
    for t in [math.pi * (0.18 + 0.08 * k) for k in range(9)]:
        for a in (a_max - 0.14, SHELL_A_MIN + 0.1):
            p, (tt, ta, n) = shell_frame_at(t, a, 0.5)
            box(F, lamp, p - n * 0.1, (0.7, 0.18, 0.18), axes=(tt, ta, n))
    for t, a in ((0.42, 0.75), (0.6, 0.25), (0.33, 0.05)):
        p, (tt, ta, n) = shell_frame_at(math.pi * t, a)
        box(F, dark, p + n * 0.05, (0.9, 2.2, 0.3), axes=(tt, ta, n))
        for k in range(5):
            box(F, paint, p + n * 0.2 + ta * (-0.8 + 0.4 * k), (1.0, 0.12, 0.3), axes=(tt, ta, n))

    if s < 0:
        S.mirror_x()
        F.mirror_x()
    shell = S.build(coll, pivot)
    sol = shell.modifiers.new('Solidify', 'SOLIDIFY')
    sol.thickness = 0.4
    sol.offset = -1.0
    sol.use_even_offset = True
    sol.material_offset = 1
    F.build(coll, pivot, bevel=0.04)

    lt = bpy.data.lights.new('MB_ShellGlow_' + name, 'POINT')
    lt.energy = 4000
    lt.color = (1.0, 0.6, 0.25)
    lt.shadow_soft_size = 1.5
    lo = bpy.data.objects.new('MB_ShellGlow_' + name, lt)
    coll.objects.link(lo)
    lo.parent = pivot
    lo.location = (s * 2.0, 0, -rz * 0.9)


# ============================================================== палуба: городок и люди
def house(P, M, x, y, w, d, h, wall, gable=False, door=-1):
    z0 = DECK_Z
    box(P, wall, (x, y, z0 + h / 2), (w, d, h))
    if gable:
        ov = 0.3
        tri = lambda yy: [V(x - w / 2 - ov, yy, z0 + h), V(x + w / 2 + ov, yy, z0 + h), V(x, yy, z0 + h + 1.1)]
        loft(P, M['roof'], [tri(y - d / 2 - ov), tri(y + d / 2 + ov)])
    else:
        box(P, M['roof'], (x, y, z0 + h + 0.12), (w + 0.4, d + 0.4, 0.24))
        box(P, wall, (x, y, z0 + h + 0.4), (w * 0.4, d * 0.4, 0.4))
    win = M['window']
    for sy in (-1, 1):
        n = max(1, int(w / 1.5))
        for k in range(n):
            wx = x - w / 2 + w * (k + 0.5) / n
            if sy == door and k == n // 2:
                box(P, win, (wx, y + sy * (d / 2 + 0.03), z0 + 1.0), (0.9, 0.08, 2.0))
            else:
                box(P, win, (wx, y + sy * (d / 2 + 0.03), z0 + h * 0.6), (0.7, 0.08, 0.9))
    for sx in (-1, 1):
        box(P, win, (x + sx * (w / 2 + 0.03), y, z0 + h * 0.6), (0.08, 0.7, 0.9))


def build_town(M):
    P = Part('MB_Town')
    dark, paint = M['dark'], M['paint']
    # перила
    for s in (-1, 1):
        x = s * 3.75
        for y in frange(-10.2, 15.3, 1.5):
            box(P, dark, (x, y, DECK_Z + 0.55), (0.07, 0.07, 1.1))
        for z in (0.55, 1.1):
            box(P, dark, (x, 2.55, DECK_Z + z), (0.05, 25.5, 0.05))
    house(P, M, -1.4, -6.2, 3.0, 3.4, 2.7, M['green'])
    house(P, M, 0.9, -0.8, 4.2, 3.4, 3.0, M['brick'], gable=True)
    house(P, M, 1.6, 12.0, 3.0, 2.6, 3.2, M['brick'])
    for (x, y, sx, sy, sz) in ((-2.6, -9.6, 1.3, 1.3, 1.3), (2.7, -8.8, 1.0, 1.0, 1.0),
                               (-2.8, 5.5, 1.2, 1.6, 1.1), (2.6, 8.0, 1.6, 1.2, 1.0), (-2.5, 13.5, 1.0, 1.0, 1.4)):
        box(P, paint, (x, y, DECK_Z + sz / 2), (sx, sy, sz))
    for (x, y) in ((-1.2, 9.0), (-0.6, 9.3), (-1.0, 9.9)):
        cyl(P, dark, (x, y, DECK_Z + 0.5), UP, 0.3, 1.0, 12)
    # мачта с фонарём на корме
    rod(P, dark, V(2.9, 14.6, DECK_Z), V(2.9, 14.6, DECK_Z + 4.5), 0.12)
    box(P, M['lamp'], (2.9, 14.6, DECK_Z + 4.6), (0.4, 0.4, 0.3))
    return P


def person(P, mat, x, y, rot):
    z0 = DECK_Z
    r = math.radians(rot)
    X, Y = V(math.cos(r), math.sin(r), 0), V(-math.sin(r), math.cos(r), 0)
    c = V(x, y, z0)
    for sg in (-1, 1):
        box(P, mat, c + X * sg * 0.1 + UP * 0.43, (0.14, 0.18, 0.86), axes=(X, Y, UP))
        box(P, mat, c + X * sg * 0.27 + UP * 1.13, (0.1, 0.12, 0.62), axes=(X, Y, UP))
    box(P, mat, c + UP * 1.17, (0.42, 0.24, 0.66), axes=(X, Y, UP))
    ellipsoid(P, mat, c + UP * 1.62, (0.12, 0.12, 0.13), 8, 6)


def build_people(M):
    P = Part('MB_People')
    for x, y, r in ((-0.5, -3.2, 10), (0.3, -3.3, 190), (1.8, 3.6, 80), (2.3, 3.8, 260),
                    (-1.3, -9.4, 30), (2.6, -5.2, 120), (-2.2, 7.4, 300), (0.6, 10.2, 0), (-0.2, 1.8, 140)):
        person(P, M['person'], x, y, r)
    return P


# ============================================================== сцена
def remove_collection(c):
    for child in list(c.children):
        remove_collection(child)
    for ob in list(c.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.collections.remove(c)


def clear_previous():
    if CLEAR_SCENE:
        for ob in list(bpy.context.scene.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
    old = bpy.data.collections.get('MechBeetle')
    if old:
        remove_collection(old)
    for coll in (bpy.data.meshes, bpy.data.lights, bpy.data.cameras, bpy.data.materials):
        for blk in list(coll):
            if blk.users == 0 and blk.name.startswith('MB_'):
                coll.remove(blk)


def set_engine(scene):
    if RENDER_ENGINE.upper() == 'CYCLES':
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = 128
        try:
            scene.cycles.use_denoising = True
        except AttributeError:
            pass
        return
    for eng in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
        try:
            scene.render.engine = eng
            break
        except TypeError:
            continue
    for attr, val in (('use_gtao', True), ('use_bloom', True), ('use_soft_shadows', True),
                      ('shadow_cascade_size', '4096'), ('taa_render_samples', 64)):
        try:
            setattr(scene.eevee, attr, val)
        except (AttributeError, TypeError):
            pass


def setup_scene(M, coll):
    scene = bpy.context.scene
    g = Part('MB_Ground')
    g.add([V(-300, -300, 0), V(300, -300, 0), V(300, 300, 0), V(-300, 300, 0)], [(0, 1, 2, 3)], M['ground'])
    g.build(coll)

    sun_data = bpy.data.lights.new('MB_Sun', 'SUN')
    sun_data.energy = 4.0
    sun_data.angle = math.radians(4)
    sun = bpy.data.objects.new('MB_Sun', sun_data)
    coll.objects.link(sun)
    sun.rotation_euler = V(0.55, 0.65, -0.8).normalized().to_track_quat('-Z', 'Y').to_euler()

    cam_data = bpy.data.cameras.new('MB_Camera')
    cam_data.lens = 50
    cam_data.clip_end = 1000
    cam = bpy.data.objects.new('MB_Camera', cam_data)
    coll.objects.link(cam)
    target = V(0, 1.5, 6.5)
    az, el, dist = math.radians(32), math.radians(33), 110.0
    cam.location = target + V(math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)) * dist
    cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam

    world = scene.world or bpy.data.worlds.new('World')
    scene.world = world
    try:
        world.use_nodes = True
    except AttributeError:
        pass
    bg = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None)
    if bg:
        bg.inputs['Color'].default_value = (0.86, 0.78, 0.64, 1.0)
        bg.inputs['Strength'].default_value = 0.9
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1000
    for look in ('AgX - Medium High Contrast', 'Medium High Contrast'):
        try:
            scene.view_settings.look = look
            break
        except TypeError:
            continue
    set_engine(scene)

    # вьюпорт: материалы и вид из камеры
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                for sp in area.spaces:
                    if sp.type == 'VIEW_3D':
                        sp.shading.type = 'MATERIAL'
                        sp.clip_end = 2000
                        sp.region_3d.view_perspective = 'CAMERA'
    except Exception:
        pass


def main():
    clear_previous()
    main_coll = bpy.data.collections.new('MechBeetle')
    bpy.context.scene.collection.children.link(main_coll)
    colls = {}
    for key in ('Body', 'Legs', 'Shells', 'Town', 'Env'):
        c = bpy.data.collections.new('MB_' + key)
        main_coll.children.link(c)
        colls[key] = c

    M = make_materials()
    root = bpy.data.objects.new('MB_Root', None)
    root.empty_display_size = 5
    colls['Body'].objects.link(root)

    build_hull(M).build(colls['Body'], root, bevel=0.08)
    build_deck(M).build(colls['Body'], root, bevel=0.03)
    build_legs(M, colls['Legs'], root)
    build_shell(M, -1, SHELL_OPEN_R, colls['Shells'], root)
    build_shell(M, 1, SHELL_OPEN_L, colls['Shells'], root)
    if BUILD_TOWN:
        build_town(M).build(colls['Town'], root, bevel=0.02)
    if BUILD_PEOPLE:
        build_people(M).build(colls['Town'], root)
    if SETUP_SCENE:
        setup_scene(M, colls['Env'])
    bpy.context.view_layer.update()
    print('MechBeetle: готово, объектов:', len(main_coll.all_objects))


main()
