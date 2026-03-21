import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import platform

# OS별 한글 폰트 자동 감지
def _get_korean_font():
    system = platform.system()
    if system == 'Darwin':
        candidates = ['Apple SD Gothic Neo', 'AppleGothic']
    elif system == 'Windows':
        candidates = ['Malgun Gothic', 'NanumGothic']
    else:
        candidates = ['NanumGothic', 'Noto Sans CJK KR']
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            return name
    return candidates[0]

_KR_FONT = _get_korean_font()
print(f"Using Korean font: {_KR_FONT}")
plt.rcParams['font.family'] = [_KR_FONT]
plt.rcParams['axes.unicode_minus'] = False  # 마이너스 기호 깨짐 방지

# 데이터 생성
x = np.linspace(0, 10, 100)
y = np.sin(x)

# 그래프 생성
plt.figure(figsize=(10, 6))
plt.plot(x, y, label='사인 함수')
plt.plot(x, -y, label='-사인 함수')
plt.title('한글 테스트: 사인 함수 그래프')
plt.xlabel('x축 라벨')
plt.ylabel('y축 라벨')
plt.legend()
plt.grid(True)
plt.savefig('korean_font_test.png')
plt.show()

print("테스트 완료! korean_font_test.png 파일을 확인하세요.")
