"""GUI 배치와 구면 좌표의 카메라 평면 투영."""
import math
import tkinter as tk
from tkinter import ttk


def frame_size(focal, zoom, ratio):
    if not (math.isfinite(focal) and focal > 0 and math.isfinite(zoom) and 1 <= zoom <= 10):
        raise ValueError('초점거리는 양수, 줌은 1~10 사이여야 합니다.')
    # 35mm 환산은 대각선 화각 기준. 4:3 기본 프레임의 대각선을 36×24mm와 맞춘다.
    diagonal = math.hypot(36, 24)
    width, height = diagonal * 4 / 5, diagonal * 3 / 5
    aspect = {'4:3': 4 / 3, '16:9': 16 / 9, '1:1': 1}[ratio]
    width, height = min(width, height * aspect), min(height, width / aspect)
    # 디지털 줌은 프레임을 잘라내므로 tan(반화각)을 줌 배율로 나눈다.
    return width / (2 * focal * zoom), height / (2 * focal * zoom)


def vector(ra, dec):
    a, d = math.radians(ra), math.radians(dec)
    return math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def basis(ra, dec):
    a, d = math.radians(ra), math.radians(dec)
    return vector(ra, dec), (-math.sin(a), math.cos(a), 0), (
        -math.sin(d) * math.cos(a), -math.sin(d) * math.sin(a), math.cos(d))


def project(point, axes):
    forward, east, north = axes
    distance = dot(point, forward)
    if distance <= 1e-10:
        return None  # 카메라 뒤쪽 또는 투영면과 평행한 방향은 표현할 수 없다.
    return dot(point, east) / distance, dot(point, north) / distance


def contained(obj, axes, half):
    point = vector(obj['ra'], obj['dec'])
    forward, east, north = (dot(point, axis) for axis in axes)
    hx, hy = half
    # 원형 각크기 전체가 네 경계 평면의 안쪽에 있는지 구면에서 판정한다.
    margin = min((hx * forward - abs(east)) / math.hypot(1, hx),
                 (hy * forward - abs(north)) / math.hypot(1, hy))
    radius = math.radians((obj['diameter'] or 0) / 2)
    return forward > 0 and margin >= math.sin(radius)


def layout(app):
    app.root.title('AstroPhone · 천체 촬영 구도 미리보기')
    width = min(1100, app.root.winfo_screenwidth() - 80)
    height = min(780, app.root.winfo_screenheight() - 100)
    app.root.geometry(f'{width}x{height}+20+20')
    app.root.minsize(min(900, width), min(650, height))
    top = ttk.Frame(app.root, padding=10)
    top.pack(fill='x')
    app.locked = []
    for column, (label, key, callback) in enumerate([
            ('제조사', 'brand', app.change_brand), ('기종', 'model', app.change_model),
            ('렌즈 · 35mm 환산', 'lens', app.draw)]):
        ttk.Label(top, text=label).grid(row=0, column=column, sticky='w')
        box = ttk.Combobox(top, state='readonly', width=30)
        box.grid(row=1, column=column, padx=(0, 8), sticky='ew')
        box.bind('<<ComboboxSelected>>', callback)
        setattr(app, key, box)
        app.locked.append((box, 'readonly'))
        top.columnconfigure(column, weight=1)
    controls = ttk.Frame(app.root, padding=(10, 0))
    controls.pack(fill='x')
    app.zoom = tk.StringVar(value='1')
    ttk.Label(controls, text='디지털 줌 (1~10)').pack(side='left')
    ttk.Spinbox(controls, from_=1, to=10, increment=.1, width=6,
                textvariable=app.zoom, command=app.draw).pack(side='left', padx=5)
    app.zoom.trace_add('write', app.draw)
    app.ratio = ttk.Combobox(controls, values=('4:3', '16:9', '1:1'), state='readonly', width=6)
    app.ratio.set('4:3')
    app.ratio.pack(side='left', padx=5)
    app.ratio.bind('<<ComboboxSelected>>', app.draw)
    app.time = ttk.Entry(controls, width=22)
    app.time.insert(0, app.now())
    app.time.pack(side='left', padx=5)
    app.locked.append((app.time, 'normal'))
    app.button(controls, 'KST 시각 적용', app.refresh)
    ttk.Label(controls, text='YYYY-MM-DD HH:mm:ss').pack(side='left')
    search = ttk.Frame(app.root, padding=10)
    search.pack(fill='x')
    app.source = ttk.Combobox(search, values=('SIMBAD', 'Horizons'), state='readonly', width=12)
    app.source.set('SIMBAD')
    app.source.pack(side='left')
    app.name = ttk.Entry(search, width=30)
    app.name.pack(side='left', padx=5)
    app.name.bind('<Return>', app.search)
    app.locked.extend([(app.name, 'normal'), (app.source, 'readonly')])
    app.button(search, '천체 추가', app.search)
    app.button(search, '휴대폰 목록 재조회', app.load_phones)
    body = ttk.Panedwindow(app.root, orient='horizontal')
    body.pack(fill='both', expand=True, padx=10)
    side = ttk.Frame(body)
    app.objects = tk.Listbox(side, width=43, exportselection=False)
    app.objects.pack(fill='both', expand=True)
    app.button(side, '선택 천체를 화면 중심으로', app.center_selected)
    app.button(side, '선택 삭제', app.remove)
    app.button(side, '전체 삭제', app.clear)
    app.canvas = tk.Canvas(body, bg='#101827', highlightthickness=0)
    app.canvas.bind('<Configure>', app.draw)
    body.add(side, weight=1)
    body.add(app.canvas, weight=4)
    app.status = tk.StringVar(value='준비 중')
    ttk.Label(app.root, textvariable=app.status, wraplength=1050, padding=10).pack(fill='x')
    ttk.Label(app.root, text='북쪽 ↑ · 동쪽 ← | 지구 중심 ICRF | 원: 제공된 각지름/장축의 외접원 · 점: 크기 미제공',
              padding=(10, 0, 10, 8)).pack(fill='x')


def render(app):
    canvas = app.canvas
    canvas.delete('all')
    width, height = canvas.winfo_width(), canvas.winfo_height()
    app.objects.delete(0, 'end')
    for obj in app.items:
        app.objects.insert('end', f'{obj["name"]} | 화각 미선택/계산 불가')
    if not app.lens_rows or app.lens.current() < 0:
        canvas.create_text(width / 2, height / 2, text='제조사 → 기종 → 렌즈를 선택하세요.', fill='white')
        return
    try:
        focal = float(app.lens_rows[app.lens.current()]['focalLength'])
        half = frame_size(focal, float(app.zoom.get()), app.ratio.get())
    except (ValueError, TypeError, KeyError):
        canvas.create_text(width / 2, height / 2, text='초점거리 미제공 또는 잘못된 줌입니다.', fill='#ffbe70')
        return
    center = app.items[app.center] if app.items else dict(ra=0, dec=0)
    axes = basis(center['ra'], center['dec'])
    points = [project(vector(o['ra'], o['dec']), axes) for o in app.items]
    # 프레임 밖 천체도 함께 볼 수 있도록 보기 범위만 확장한다. 촬영 화각은 유지된다.
    ex, ey = half
    for point in points:
        if point:
            ex, ey = max(ex, abs(point[0])), max(ey, abs(point[1]))
    scale = min(max(1, width - 100) / (2.5 * ex), max(1, height - 100) / (2.5 * ey))
    def screen(point):
        return width / 2 - point[0] * scale, height / 2 - point[1] * scale
    hx, hy = half
    canvas.create_rectangle(*screen((hx, hy)), *screen((-hx, -hy)), outline='#66e3c4', width=2)
    fov = tuple(math.degrees(2 * math.atan(v)) for v in half)
    canvas.create_text(12, 12, anchor='nw', fill='white', text=f'촬영 화각 {fov[0]:.2f}° × {fov[1]:.2f}° · 중심: {center.get("name", "미선택")}\n계산 시각(KST): {app.applied}')
    app.objects.delete(0, 'end')
    for obj, point in zip(app.items, points):
        inside = contained(obj, axes, half)
        label = ('외접원 안' if obj['diameter'] else '중심 안·크기 미제공') if inside else '프레임 밖/경계'
        if point is None:
            label = '뒤쪽 반구·투영 불가'
        app.objects.insert('end', f'{obj["name"]} | {label}')
        if point is None:
            continue
        x, y = screen(point)
        color = '#8bf0c2' if inside else '#ffbe70'
        if obj['diameter']:
            local = basis(obj['ra'], obj['dec'])
            radius = math.radians(obj['diameter'] / 2)
            outline = []
            for step in range(73):
                angle = step * math.tau / 72
                edge = tuple(math.cos(radius) * local[0][j] + math.sin(radius) * (
                    math.cos(angle) * local[1][j] + math.sin(angle) * local[2][j]) for j in range(3))
                projected = project(edge, axes)
                if projected is None:
                    outline = []
                    break
                outline.extend(screen(projected))
            if outline:
                canvas.create_line(*outline, fill=color)
        canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline=color)
        canvas.create_text(x + 7, y - 10, text=obj['name'], anchor='w', fill=color)
