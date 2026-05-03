"""
앱 시작 시 1회 실행 — 한글 폰트를 matplotlib fonts/ttf 디렉터리에 설치
실패해도 앱 시작을 막지 않도록 모든 오류를 경고로만 출력
Streamlit Community Cloud: packages.txt의 fonts-nanum으로 시스템 설치된 폰트 우선 사용
"""
import os, shutil, urllib.request
import matplotlib
import matplotlib.font_manager as fm

FONT_URL  = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
TMP_PATH  = "/tmp/NanumGothic.ttf"

# Streamlit Cloud에서 packages.txt(fonts-nanum)로 설치되는 시스템 폰트 경로
SYSTEM_FONT_PATHS = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/nanum/NanumGothic.ttf",
]

def _find_font_source() -> str | None:
    """시스템 설치 폰트 → 이미 다운된 파일 → None 순으로 반환"""
    for p in SYSTEM_FONT_PATHS:
        if os.path.exists(p):
            print(f"[setup_fonts] System font found: {p}")
            return p
    if os.path.exists(TMP_PATH):
        print(f"[setup_fonts] Cached font found: {TMP_PATH}")
        return TMP_PATH
    return None

def main():
    # 1) 폰트 파일 확보 (시스템 우선, 없으면 다운로드)
    font_src = _find_font_source()
    if font_src is None:
        try:
            print(f"[setup_fonts] Downloading NanumGothic → {TMP_PATH}")
            urllib.request.urlretrieve(FONT_URL, TMP_PATH)
            font_src = TMP_PATH
        except Exception as e:
            print(f"[setup_fonts] WARNING: Font download failed: {e}")
            return

    # 2) matplotlib fonts/ttf 디렉터리에 복사 (read-only 환경 대비)
    try:
        mpl_font_dir = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        dest = os.path.join(mpl_font_dir, "NanumGothic.ttf")
        if not os.path.exists(dest):
            shutil.copy(font_src, dest)
            print(f"[setup_fonts] Copied to {dest}")
    except Exception as e:
        print(f"[setup_fonts] WARNING: Could not copy font to mpl dir: {e}")

    # 3) matplotlib 폰트 캐시 재빌드 (matplotlib 버전 호환)
    try:
        cache_dir = matplotlib.get_cachedir()
        for f in os.listdir(cache_dir):
            if f.startswith("fontlist"):
                try:
                    os.remove(os.path.join(cache_dir, f))
                    print(f"[setup_fonts] Removed cache: {f}")
                except Exception:
                    pass

        # matplotlib 3.9+ 에서는 _load_fontmanager 제거됨
        if hasattr(fm, "_load_fontmanager"):
            fm._load_fontmanager(try_read_cache=False)
        else:
            fm.fontManager = fm.FontManager()
        print("[setup_fonts] Font cache rebuilt. Done.")
    except Exception as e:
        print(f"[setup_fonts] WARNING: Font cache rebuild failed: {e}")

if __name__ == "__main__":
    main()
