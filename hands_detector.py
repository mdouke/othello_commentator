import cv2
import mediapipe as mp
import sys                          # ★追加

mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils

hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

cap = cv2.VideoCapture(0)

prev_hand = False                   # ★前フレームの有無

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        print("カメラから映像を取得できませんでした", file=sys.stderr, flush=True)
        break

    image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = hands.process(image)

    hand_now = bool(result.multi_hand_landmarks)   # ★今回の有無

    # 状態が変わったときだけ stdout に出力
    if hand_now and not prev_hand:
        print("Hand Detected", flush=True)
    elif not hand_now and prev_hand:
        print("No Hand", flush=True)
    prev_hand = hand_now

    # ------ 以下はデバッグ用の可視化 ----------
    if hand_now:
        for hand_landmarks in result.multi_hand_landmarks:
            mp_drawing.draw_landmarks(
                frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)
        cv2.putText(frame, "Hand Detected", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    else:
        cv2.putText(frame, "No Hand", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

    cv2.imshow("Hand Detection", frame)
    if cv2.waitKey(1) & 0xFF == 27:
        break
# ------------------------------------------

cap.release()
cv2.destroyAllWindows()
hands.close()
