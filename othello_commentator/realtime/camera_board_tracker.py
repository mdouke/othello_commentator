# camera_board_tracker.py
from __future__ import annotations
import cv2, numpy as np
from typing import List, Tuple

SIZE = 400
CELL = SIZE // 8
GRID_OPTS = [8,10,16,20,25,40,50,80,100]

# 皮膚色域（必要なら後で調整）
HSV_MIN = np.array(( 0,  40,  70), dtype=np.uint8)
HSV_MAX = np.array((25, 255, 255), dtype=np.uint8)
SKIN_THR_PCT = 0.20

def _extract_roi(cell, m=10):
    h, w = cell.shape[:2]
    return cell[m:h-m, m:w-m]

def _hand_grid(board_hsv, grid_n:int, cell_sz:int) -> list[list[bool]]:
    mask = cv2.inRange(board_hsv, HSV_MIN, HSV_MAX)
    hand = [[False]*grid_n for _ in range(grid_n)]
    for hy in range(grid_n):
        for hx in range(grid_n):
            y0,y1 = hy*cell_sz,(hy+1)*cell_sz
            x0,x1 = hx*cell_sz,(hx+1)*cell_sz
            sub = mask[y0:y1, x0:x1]
            hand[hy][hx] = (sub>0).mean() >= SKIN_THR_PCT
    return hand

class BoardTracker:
    def __init__(self, cam_id=0):
        self.cap = cv2.VideoCapture(cam_id)
        if not self.cap.isOpened():
            raise RuntimeError("Camera open failed")

        # --- 露出まわり：可能ならオートを切って固定 ---
        # ※効き方はカメラ/ドライバ依存。setが無視されることもある。
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # 0.25/0.75 どちらかが効く個体が多い
        self.cap.set(cv2.CAP_PROP_EXPOSURE, -6)         # 値域は機種依存（負値が多い）
        self.cap.set(cv2.CAP_PROP_GAIN, 0)

        # 効いてるか確認（大事）
        print("[cam] AUTO_EXPOSURE=", self.cap.get(cv2.CAP_PROP_AUTO_EXPOSURE),
            "EXPOSURE=", self.cap.get(cv2.CAP_PROP_EXPOSURE),
            "GAIN=", self.cap.get(cv2.CAP_PROP_GAIN))

        self.H = None
        self.hand_grid_idx = 5
        self.green_margin = 6
        self.delta_L = 8
        self.SHOW_RGB = False

    def _ensure_controls_window(self):
        """GREEN_MARGIN/DELTA_L/HAND_GRID のトラックバーを（なければ）作る"""
        try:
            # visible==-1 の場合は未作成/閉じられている
            if cv2.getWindowProperty("controls", cv2.WND_PROP_VISIBLE) < 0:
                raise cv2.error("controls window not visible")
        except Exception:
            cv2.namedWindow("controls")
            cv2.resizeWindow("controls", 400, 70)
            cv2.createTrackbar("GREEN_MARGIN", "controls", int(self.green_margin), 50, lambda x: None)
            cv2.createTrackbar("DELTA_L", "controls", int(self.delta_L), 30, lambda x: None)
            cv2.createTrackbar("HAND_GRID", "controls", int(self.hand_grid_idx), len(GRID_OPTS) - 1, lambda x: None)

    def capture_calib_frame(self):
        """カメラ画像からキャリブ用の静止画を取得（cキーで確定 / Escでキャンセル）"""
        print("[i] cキーで盤面静止画を確定（Escでキャンセル）")
        cv2.namedWindow("calib")
        while True:
            ret, frame = self.cap.read()
            if not ret:
                continue
            cv2.imshow("calib", frame)
            k = cv2.waitKey(1) & 0xFF
            if k == ord("c"):
                img = frame.copy()
                cv2.destroyWindow("calib")
                return img
            if k == 27:  # Esc
                cv2.destroyWindow("calib")
                return None

    def select_corners_interactive(self, image, window_name: str = "click 4 corners"):
        """画像上で四隅を4クリックして取得（Escでキャンセル、rでリセット、Enter/Spaceで確定）"""
        pts: List[List[int]] = []
        calib_img = image.copy()

        def _redraw():
            nonlocal calib_img
            calib_img = image.copy()
            for (px, py) in pts:
                cv2.circle(calib_img, (px, py), 5, (0, 0, 255), -1)
        def _on_click(evt, x, y, _f, _p):
            if evt == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
                pts.append([x, y])
                _redraw()
        cv2.namedWindow(window_name)
        cv2.setMouseCallback(window_name, _on_click)

        while True:
            cv2.imshow(window_name, calib_img)
            k = cv2.waitKey(10) & 0xFF
            if k == 27:  # Esc
                cv2.destroyWindow(window_name)
                return None
            if k == ord("r"):
                pts.clear()
                _redraw()
            if len(pts) >= 4:
                if k in (13, 10, ord(" ")):  # Enter/Return/Space
                    cv2.destroyWindow(window_name)
                    return pts

    def apply_corners(self, pts):
        """四隅4点から透視変換行列Hを更新"""
        if pts is None or len(pts) != 4:
            raise ValueError("apply_corners expects 4 points")
        self.H = cv2.getPerspectiveTransform(
            np.float32(pts),
            np.float32([[0, 0], [SIZE, 0], [SIZE, SIZE], [0, SIZE]])
        )

    def calibrate(self):
        """ゲーム開始前のキャリブ（静止画→四隅クリック→H更新→controls作成）"""
        calib_img = self.capture_calib_frame()
        if calib_img is None:
            print("[i] calib canceled")
            return False

        pts = self.select_corners_interactive(calib_img)
        if pts is None:
            print("[i] corner selection canceled")
            return False

        self.apply_corners(pts)
        self._ensure_controls_window()
        return True

    def read_board(self):
        self._ensure_controls_window()
        ret, frame = self.cap.read()
        if not ret: 
            return None
        board = cv2.warpPerspective(frame, self.H, (SIZE,SIZE))
        self.green_margin = cv2.getTrackbarPos("GREEN_MARGIN", "controls")
        self.delta_L      = cv2.getTrackbarPos("DELTA_L", "controls")
        self.hand_grid_idx= cv2.getTrackbarPos("HAND_GRID", "controls")
        return board

    def detect_hand(self, board) -> bool:
        """盤面上に手（肌色）があるかだけを判定"""
        hsv = cv2.cvtColor(board, cv2.COLOR_BGR2HSV)

        grid_n = GRID_OPTS[self.hand_grid_idx]
        cell_sz = SIZE // grid_n

        hN = _hand_grid(hsv, grid_n, cell_sz)
        return any(any(r) for r in hN)

    def classify_stones(self, board) -> tuple[list[list[str]], list[list[tuple[int,int,int]]]]:
        """盤面を 'B','W','.' に分類（手は考慮しない）"""
        gm, dL = self.green_margin, self.delta_L
        lab = [["." for _ in range(8)] for _ in range(8)]
        rgb_full = [[(0,0,0) for _ in range(8)] for _ in range(8)]
        info = []

        for y in range(8):
            for x in range(8):
                cell = board[y*CELL:(y+1)*CELL, x*CELL:(x+1)*CELL]
                r0,g0,b0 = map(int, cv2.mean(cell)[:3][::-1])
                rgb_full[y][x] = (r0,g0,b0)

                roi = _extract_roi(cell)
                r,g,b = map(int, cv2.mean(roi)[:3][::-1])

                # 緑背景除外
                if g > r + gm and g > b + gm:
                    continue

                L = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)[:,:,0].mean()
                info.append(((y,x), L))

        if info:
            mn = min(L for _,L in info)
            mx = max(L for _,L in info)
            th = (mn + mx) / 2

            for (y,x), L in info:
                if L <= th - dL:
                    lab[y][x] = "B"
                elif L >= th + dL:
                    lab[y][x] = "W"
                else:
                    lab[y][x] = "."

        return lab, rgb_full
    
    def hand_mask_8x8(self, board) -> list[list[bool]]:
        """手マスクを 8x8 に集約して返す（表示・デバッグ用）"""
        hsv = cv2.cvtColor(board, cv2.COLOR_BGR2HSV)
        grid_n = GRID_OPTS[self.hand_grid_idx]
        cell_sz = SIZE // grid_n
        hN = _hand_grid(hsv, grid_n, cell_sz)

        m8 = [[False]*8 for _ in range(8)]
        for y8 in range(8):
            for x8 in range(8):
                hy0, hy1 = int(y8*grid_n/8), int((y8+1)*grid_n/8)
                hx0, hx1 = int(x8*grid_n/8), int((x8+1)*grid_n/8)
                m8[y8][x8] = any(hN[hy][hx] for hy in range(hy0,hy1) for hx in range(hx0,hx1))
        return m8

    def show_board_overlay(self, board, labels, rgb_full, show_rgb=False):
        for y in range(8):
            for x in range(8):
                y0,y1,x0,x1 = y*CELL,(y+1)*CELL,x*CELL,(x+1)*CELL
                ch = labels[y][x]

                cv2.rectangle(board,(x0,y0),(x1,y1),(120,120,120),1)

                text_pos = (x0+6, y0+22)

                if ch == "W":
                    # 黒で縁取り
                    cv2.putText(board, "W",
                                text_pos,
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.7,
                                (127,127,127),
                                4,
                                cv2.LINE_AA)
                    # 白文字
                    cv2.putText(board, "W",
                                text_pos,
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.7,
                                (255,255,255),
                                2,
                                cv2.LINE_AA)

                elif ch == "B":
                    # 白で縁取り
                    cv2.putText(board, "B",
                                text_pos,
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.7,
                                (127,127,127),
                                4,
                                cv2.LINE_AA)
                    # 黒文字
                    cv2.putText(board, "B",
                                text_pos,
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.7,
                                (0,0,0),
                                2,
                                cv2.LINE_AA)

                elif ch == "H":
                    cv2.putText(board, "H",
                                text_pos,
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.7,
                                (0,0,255),
                                2,
                                cv2.LINE_AA)

                if show_rgb:
                    r,g,b = rgb_full[y][x]
                    base = y0+32
                    cv2.putText(board, f"R{r:3d}", (x0+2, base),     cv2.FONT_HERSHEY_PLAIN, 0.8, (0,0,255), 1)
                    cv2.putText(board, f"G{g:3d}", (x0+2, base+12),  cv2.FONT_HERSHEY_PLAIN, 0.8, (0,255,0), 1)
                    cv2.putText(board, f"B{b:3d}", (x0+2, base+24),  cv2.FONT_HERSHEY_PLAIN, 0.8, (255,0,0), 1)

        cv2.imshow("board", board)

    def release(self):
        self.cap.release()
