import sys
import time
from pathlib import Path
import tkinter as tk

import av
from PIL import Image, ImageOps, ImageTk


VIDEO_PATH = Path(r"C:\Users\User\Downloads\Intro Video XEON.mp4")
START_SECONDS = 36.0
END_SECONDS = 42.0


class IntroPlayer:
    def __init__(self, video_path: Path):
        self.video_path = video_path
        self.root = tk.Tk()
        self.root.configure(bg="black")
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.bind("<Escape>", lambda _event: self.close())
        self.root.bind("<Button-1>", lambda _event: None)
        self.label = tk.Label(self.root, bg="black", bd=0, highlightthickness=0)
        self.label.pack(fill="both", expand=True)
        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()
        self.closed = False
        self.photo = None

    def close(self):
        self.closed = True
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def render_frame(self, frame):
        image = frame.to_image().convert("RGB")
        image = ImageOps.fit(image, (self.screen_w, self.screen_h), method=Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image)
        self.label.configure(image=self.photo)
        self.root.update_idletasks()
        self.root.update()

    def play(self):
        container = av.open(str(self.video_path))
        stream = next(s for s in container.streams if s.type == "video")
        stream.thread_type = "AUTO"
        if stream.time_base:
            container.seek(int(START_SECONDS / float(stream.time_base)), stream=stream, any_frame=False, backward=True)

        wall_start = None
        first_pts = None
        last_frame_time = time.monotonic()

        for frame in container.decode(stream):
            if self.closed:
                break
            if frame.time is None:
                frame_time = START_SECONDS + (time.monotonic() - last_frame_time)
            else:
                frame_time = float(frame.time)
            if frame_time < START_SECONDS:
                continue
            if frame_time > END_SECONDS:
                break
            if wall_start is None:
                wall_start = time.monotonic()
                first_pts = frame_time
            target_elapsed = max(0.0, frame_time - float(first_pts))
            sleep_for = target_elapsed - (time.monotonic() - wall_start)
            if sleep_for > 0:
                time.sleep(min(sleep_for, 0.08))
            self.render_frame(frame)
            last_frame_time = time.monotonic()

        container.close()
        self.close()


def main():
    video_path = Path(sys.argv[1]) if len(sys.argv) > 1 else VIDEO_PATH
    if not video_path.exists():
        return 0
    player = IntroPlayer(video_path)
    player.root.after(50, player.play)
    try:
        player.root.mainloop()
    except tk.TclError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
