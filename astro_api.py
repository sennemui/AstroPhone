"""HTTP 요청과 응답 검증. 좌표·각크기의 내부 단위는 도(degree)."""
import csv
import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

KST = timezone(timedelta(hours=9))
PHONE = 'https://phonecameradata.com/api/'
SIMBAD = 'https://simbad.cfa.harvard.edu/simbad/sim-tap/sync'
HORIZONS = 'https://ssd.jpl.nasa.gov/api/horizons.api'


def get_json(url, params=None):
    try:
        response = requests.get(url, params=params, timeout=(8, 30))
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ValueError('API 연결 또는 응답 오류: ' + str(exc)) from exc


def number(value, positive=False):
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError('유효하지 않은 수치입니다.')
    return result


def phones():
    rows = get_json(PHONE + 'models-index')['items']
    if not rows or any(not all(r.get(k) for k in ('brand', 'name', 'slug')) for r in rows):
        raise ValueError('제조사·기종 데이터가 없거나 형식이 변경되었습니다.')
    return rows


def lenses(slug):
    rows = get_json(PHONE + 'models/' + quote(slug, safe=''))['item']['cameras']
    if not rows:
        raise ValueError('제공된 렌즈가 없습니다.')
    # 제공 사이트의 상세 사양 표는 focalLength를 Equiv. Focal(mm)로 정의한다.
    return rows


def tap(query):
    data = get_json(SIMBAD, dict(request='doQuery', lang='adql', format='json', query=query))
    if 'data' not in data or 'metadata' not in data:
        raise ValueError('SIMBAD TAP 응답 형식이 변경되었습니다.')
    return data


def simbad(name):
    identifier = name.replace("'", "''")  # ADQL 문자열 리터럴의 작은따옴표 이스케이프
    data = tap("SELECT TOP 2 b.main_id,b.ra,b.dec,b.galdim_majaxis FROM basic AS b "
               "JOIN ident AS i ON b.oid=i.oidref WHERE i.id='" + identifier + "'")
    if not data['data']:
        raise ValueError('SIMBAD에 해당 식별자가 없습니다.')
    if len(data['data']) != 1:
        raise ValueError('SIMBAD 식별자가 유일하지 않습니다.')
    units = {m['name'].lower(): m.get('unit') for m in data['metadata']}
    if units.get('ra') != 'deg' or units.get('dec') != 'deg':
        raise ValueError('SIMBAD 좌표 단위를 확인할 수 없습니다.')
    title, ra, dec, major = data['data'][0]
    diameter = None
    if major is not None:
        if units.get('galdim_majaxis') != 'arcmin':
            raise ValueError('SIMBAD 장축 단위를 확인할 수 없습니다.')
        diameter = number(major, True) / 60  # 각분 → 도; 장축을 포함하는 외접원
    return object_data(title, ra, dec, diameter, 'SIMBAD', name)


def object_data(name, ra, dec, diameter, source, key, epoch=None):
    ra, dec = number(ra), number(dec)
    if not (0 <= ra < 360 and -90 <= dec <= 90):
        raise ValueError('좌표가 허용 범위를 벗어났습니다.')
    if diameter is not None and not (0 < diameter < 180):
        raise ValueError('각크기가 허용 범위를 벗어났습니다.')
    return dict(name=name, ra=ra, dec=dec, diameter=diameter,
                source=source, key=key, epoch=epoch)


def horizons(command, moment):
    if not command or "'" in command or '\n' in command or '\r' in command:
        raise ValueError('Horizons 검색어에 작은따옴표나 줄바꿈을 사용할 수 없습니다.')
    utc = moment.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    params = dict(format='json', COMMAND=f"'{command}'", MAKE_EPHEM="'YES'",
                  EPHEM_TYPE="'OBSERVER'", CENTER="'500@399'", TLIST=f"'{utc}'",
                  TLIST_TYPE="'CAL'", TIME_TYPE="'UT'", QUANTITIES="'1,13'",
                  ANG_FORMAT="'DEG'", CSV_FORMAT="'YES'", CAL_TYPE="'GREGORIAN'")
    data = get_json(HORIZONS, params)
    text = data.get('result', '')
    if 'Multiple major-bodies match' in text:
        # API의 고정 폭 후보 표에서 ID와 이름을 읽는다. 미리 만든 ID 목록은 없다.
        candidates = []
        for line in text.splitlines():
            match = re.match(r'^\s*(-?\d+)\s{2,}(.{1,34})', line)
            if match:
                candidates.append((match[1], match[2].strip()))
        if not candidates:
            raise ValueError('Horizons 후보 표를 해석할 수 없습니다.')
        return candidates
    if data.get('error') or '$$SOE' not in text or '$$EOE' not in text:
        raise ValueError('Horizons 조회 실패: ' + str(data.get('error') or text)[:600])
    if 'R.A._(ICRF)' not in text or 'Ang-diam' not in text or 'ARCSECONDS' not in text:
        raise ValueError('Horizons 좌표·각지름 형식이 변경되었습니다.')
    title = re.search(r'Target body name:\s*(.*?)\s*\{', text)
    if not title:
        raise ValueError('Horizons 대상 이름과 ID를 확인할 수 없습니다.')
    lines = text.split('$$SOE', 1)[1].split('$$EOE', 1)[0].strip().splitlines()
    if len(lines) != 1:
        raise ValueError('요청 시각의 단일 좌표를 받지 못했습니다.')
    row = next(csv.reader(lines))
    # 실제 CSV: UT 시각, 공란, 공란, 적경(도), 적위(도), 각지름(각초), 공란
    diameter = None if row[5].strip() == 'n.a.' else number(row[5], True) / 3600
    return object_data(title[1].strip(), row[3], row[4], diameter,
                       'Horizons', command, moment.isoformat())


def parse_time(text):
    return datetime.strptime(text, '%Y-%m-%d %H:%M:%S').replace(tzinfo=KST)
