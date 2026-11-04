"""실행: uv run python astrophone.py. 네트워크 처리는 daemon 스레드에서 실행한다."""
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk

import astro_api as api
import astro_view as view


class App:
    def __init__(self, root):
        self.root = root
        self.items, self.phone_rows, self.model_rows, self.lens_rows = [], [], [], []
        self.center, self.busy, self.closed = 0, False, False
        self.results = queue.Queue()
        self.applied = self.now()
        view.layout(self)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = root.after(80, self.poll)
        self.load_phones()

    def now(self):
        return datetime.now(api.KST).strftime('%Y-%m-%d %H:%M:%S')

    def button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        side = 'top' if hasattr(self, 'objects') and parent is self.objects.master else 'left'
        button.pack(side=side, padx=3, pady=3)
        self.locked.append((button, 'normal'))

    def run(self, work, done):
        if self.busy:
            return
        self.busy = True
        self.status.set('API 조회 중… 창 크기 조절과 줌·비율 변경은 가능합니다.')
        for widget, state in self.locked:
            widget.configure(state='disabled')
        def worker():
            try:
                result = (done, work(), None)
            except Exception as exc:
                result = (done, None, str(exc))
            self.results.put(result)  # worker에서는 Tk 위젯에 접근하지 않는다.
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            done, value, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for widget, state in self.locked:
                widget.configure(state=state)
            if error:
                self.status.set('조회 실패: ' + error)
            else:
                try:
                    self.status.set('조회 완료')
                    done(value)
                except (ValueError, KeyError, TypeError, IndexError) as exc:
                    self.status.set('데이터 처리 실패: ' + str(exc))
        if not self.closed:
            self.poll_id = self.root.after(80, self.poll)

    def load_phones(self):
        self.run(api.phones, self.set_phones)

    def set_phones(self, rows):
        self.phone_rows = rows
        self.brand['values'] = sorted({r['brand'] for r in rows})
        self.brand.set('')
        self.model.set('')
        self.model['values'] = ()
        self.lens.set('')
        self.lens_rows = []
        self.draw()
        self.status.set(f'{len(rows)}개 기종을 불러왔습니다. 제조사를 선택하세요.')

    def change_brand(self, event=None):
        self.model_rows = [r for r in self.phone_rows if r['brand'] == self.brand.get()]
        self.model['values'] = [r.get('displayNameEn') or r['name'] for r in self.model_rows]
        self.model.set('')
        self.lens.set('')
        self.lens['values'] = ()
        self.lens_rows = []
        self.draw()

    def change_model(self, event=None):
        index = self.model.current()
        if index < 0:
            return
        self.lens_rows = []
        self.lens.set('')
        self.draw()
        self.run(lambda: api.lenses(self.model_rows[index]['slug']), self.set_lenses)

    def set_lenses(self, rows):
        self.lens_rows = rows
        self.lens['values'] = [f'{r.get("type", "이름 미제공")} · {r.get("focalLength", "미제공")} mm' for r in rows]
        self.lens.set('')
        self.status.set('렌즈를 선택하세요. 초점거리가 없으면 화각을 계산하지 않습니다.')

    def search(self, event=None):
        if self.busy:
            return
        name = self.name.get().strip()
        if not name:
            self.status.set('정확한 천체 이름/식별자를 입력하세요.')
            return
        try:
            moment = api.parse_time(self.time.get())
            if self.time.get() != self.applied and self.items:
                raise ValueError('먼저 KST 시각 적용을 눌러 기존 천체와 시각을 맞추세요.')
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.applied = self.time.get()
        work = (lambda: api.simbad(name)) if self.source.get() == 'SIMBAD' else (lambda: api.horizons(name, moment))
        self.run(work, self.add_result)

    def add_result(self, result):
        if isinstance(result, list):
            self.choose(result)
            return
        if any(o['source'] == result['source'] and o['name'] == result['name'] for o in self.items):
            self.status.set('이미 추가한 천체입니다.')
            return
        self.items.append(result)
        self.draw()
        self.status.set('추가 완료 · 좌표/각크기: ' + result['source'] + ' · 계산 시각(KST): ' + self.applied)

    def choose(self, candidates):
        dialog = tk.Toplevel(self.root)
        dialog.title('Horizons 대상 선택 · API 반환 이름과 ID')
        dialog.transient(self.root)
        dialog.grab_set()
        box = tk.Listbox(dialog, width=65, height=min(12, len(candidates)), exportselection=False)
        box.pack(padx=15, pady=15)
        for key, name in candidates:
            box.insert('end', f'{name} · ID {key}')
        def select():
            if not box.curselection():
                return
            key = candidates[box.curselection()[0]][0]
            moment = api.parse_time(self.applied)
            dialog.destroy()
            self.run(lambda: api.horizons(key, moment), self.add_result)
        ttk.Button(dialog, text='이 대상으로 조회', command=select).pack(pady=10)

    def refresh(self):
        try:
            moment = api.parse_time(self.time.get())
        except ValueError:
            self.status.set('시각 형식: YYYY-MM-DD HH:mm:ss (한국 시간)')
            return
        def work():
            rows = [api.horizons(o['key'], moment) if o['source'] == 'Horizons' else o.copy() for o in self.items]
            if any(isinstance(o, list) for o in rows):
                raise ValueError('기존 Horizons 대상 ID가 유일하지 않습니다.')
            return rows
        def done(rows):
            self.items = rows  # 전체 성공 시에만 교체하여 서로 다른 시각의 좌표 혼합을 방지한다.
            self.applied = self.time.get()
            self.draw()
            self.status.set('전체 천체의 계산 시각(KST): ' + self.applied)
        self.run(work, done)

    def center_selected(self):
        if self.objects.curselection():
            self.center = self.objects.curselection()[0]
            self.draw()

    def remove(self):
        if self.objects.curselection():
            del self.items[self.objects.curselection()[0]]
            self.center = 0
            self.draw()

    def clear(self):
        self.items.clear()
        self.center = 0
        self.draw()

    def draw(self, *args):
        view.render(self)

    def close(self):
        self.closed = True
        self.root.after_cancel(self.poll_id)
        self.root.destroy()  # daemon 통신 스레드가 끝날 때까지 창을 붙잡지 않는다.


if __name__ == '__main__':
    App(tk.Tk()).root.mainloop()
