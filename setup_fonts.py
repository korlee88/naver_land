"""
Railway 시작 시 1회 실행 — 한글 폰트를 matplotlib fonts/ttf 디렉터리에 설치
"""
import os, shutil, urllib.request
import matplotlib
import matplotlib.font_manager as fm

FONT_URL  = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
TMP_PATH  = "/tmp/NanumGothic.ttf"

def main():
    # 1) 폰트 파일 다운로드
    if not os.path.exists(TMP_PATH):
        print(f"[setup_fonts] Downloading NanumGothic → {TMP_PATH}")
        urllib.request.urlretrieve(FONT_URL, TMP_PATH)
    else:
        print(f"[setup_fonts] Font already exists: {TMP_PATH}")

    # 2) matplotlib fonts/ttf 디렉터리에 복사
    mpl_font_dir = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    dest = os.path.join(mpl_font_dir, "NanumGothic.ttf")
    if not os.path.exists(dest):
        shutil.copy(TMP_PATH, dest)
        print(f"[setup_fonts] Copied to {dest}")

    # 3) matplotlib 폰트 캐시 재빌드
    cache_dir = matplotlib.get_cachedir()
    for f in os.listdir(cache_dir):
        if f.startswith("fontlist"):
            os.remove(os.path.join(cache_dir, f))
            print(f"[setup_fonts] Removed cache: {f}")

    fm._load_fontmanager(try_read_cache=False)
    print("[setup_fonts] Font cache rebuilt. Done.")

if __name__ == "__main__":
    main()
