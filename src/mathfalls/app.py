from __future__ import annotations

import os
import sys
import time
import math
import shutil
from array import array
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import tempfile

_temp_dir = Path(tempfile.gettempdir())
os.environ.setdefault("MPLCONFIGDIR", str(_temp_dir / "mathfalls-mpl"))
os.environ.setdefault("XDG_CACHE_HOME", str(_temp_dir / "mathfalls-cache"))

import pygame

from .camera import CameraTracker, FaceState, discover_cameras
from .game import MathGame, PlayerGame
from .leaderboard import Leaderboard


WIDTH = 1280
HEIGHT = 720
FPS = 60
DB_PATH = Path.home() / ".mathfalls" / "leaderboard.sqlite3"

BG = (12, 18, 24)
PANEL = (24, 32, 42)
PANEL_2 = (30, 42, 52)
TEXT = (238, 242, 246)
MUTED = (151, 164, 176)
BLUE = (71, 149, 240)
GREEN = (82, 183, 136)
YELLOW = (255, 202, 58)
RED = (239, 83, 80)
INK = (6, 10, 14)

KEYS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") + ["DEL", "OK"]
DIFFICULTY_RELEASE_SECONDS = 0.35
DIFFICULTY_CONFIRM_SECONDS = 0.55


class SoundFx:
    def __init__(self) -> None:
        self.enabled = False
        self.sounds = {}
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
            self.sounds = {
                "click": _tone(560, 0.055, 0.35),
                "start": _tone(740, 0.14, 0.35),
                "catch": _tone(880, 0.075, 0.35),
                "danger": _tone(180, 0.18, 0.45),
                "done": _tone(660, 0.16, 0.35),
            }
            self.enabled = True
        except pygame.error as exc:
            print(f"Sonidos deshabilitados: {exc}")

    def play(self, name: str) -> None:
        if self.enabled and name in self.sounds:
            self.sounds[name].play()


class NicknamePad:
    def __init__(self, label: str) -> None:
        self.label = label
        self.name = ""
        self.focus = 0
        self.done = False

    def press(self, key: str | None = None) -> None:
        if self.done:
            return
        key = key or KEYS[self.focus]
        if key == "DEL":
            self.name = self.name[:-1]
        elif key == "OK":
            self.done = len(self.name.strip()) > 0
        elif len(self.name) < 12:
            self.name += key

    @property
    def nickname(self) -> str:
        return self.name.strip() or self.label


class MathFallsApp:
    def __init__(self) -> None:
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_caption("MathFalls")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Arial", 28)
        self.big = pygame.font.SysFont("Arial", 60, bold=True)
        self.mid = pygame.font.SysFont("Arial", 38, bold=True)
        self.small = pygame.font.SysFont("Arial", 20)
        self.logo = _load_logo()
        if self.logo is not None:
            pygame.display.set_icon(self.logo)
        self.sounds = SoundFx()

        self.leaderboard = Leaderboard(_leaderboard_path())
        self.available_cameras = discover_cameras()
        self.selected_camera = self.available_cameras[0]
        self.camera: CameraTracker | None = None
        self.state = "camera_select"
        self.start_since: float | None = None
        self.mode_candidate: int | None = None
        self.player_count = 2
        self.difficulty_level = 4
        self.difficulty_phase = "release"
        self.difficulty_candidate: int | None = None
        self.difficulty_since: float | None = None
        self.release_since: float | None = None
        self.pads = [NicknamePad("PLAYER 1"), NicknamePad("PLAYER 2")]
        self.nickname_index = 0
        self.pointer_pos = (WIDTH // 2, HEIGHT // 2)
        self.game: MathGame | None = None
        self.saved_scores = False

    def run(self) -> None:
        running = True
        last = time.monotonic()
        try:
            while running:
                now = time.monotonic()
                dt = now - last
                last = now

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        running = False
                    else:
                        self._handle_event(event)

                faces: list[FaceState] = []
                if self.camera is not None:
                    _, faces = self.camera.read()
                self._update(dt, faces)
                self._draw(faces)
                pygame.display.flip()
                self.clock.tick(FPS)
        finally:
            if self.camera is not None:
                self.camera.close()
            pygame.quit()

    def _handle_event(self, event: pygame.event.Event) -> None:
        if self.state == "camera_select":
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                    self._move_camera_selection(1)
                elif event.key in (pygame.K_LEFT, pygame.K_UP):
                    self._move_camera_selection(-1)
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self._activate_camera(self.selected_camera)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for index, camera_index in enumerate(self.available_cameras):
                    if _camera_button_rect(index, len(self.available_cameras)).collidepoint(event.pos):
                        self._activate_camera(camera_index)
                        break
        elif self.state == "game_over":
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._return_to_leaderboard()

    def _move_camera_selection(self, direction: int) -> None:
        current = self.available_cameras.index(self.selected_camera)
        self.selected_camera = self.available_cameras[(current + direction) % len(self.available_cameras)]

    def _activate_camera(self, camera_index: int) -> None:
        if self.camera is not None:
            self.camera.close()
        self.selected_camera = camera_index
        self.camera = CameraTracker(camera_index)
        self.state = "leaderboard"
        self.sounds.play("start")

    def _update(self, dt: float, faces: list[FaceState]) -> None:
        if self.state == "camera_select":
            return
        if self.state == "leaderboard":
            self._update_leaderboard(faces)
        elif self.state == "difficulty":
            self._update_difficulty()
        elif self.state == "nickname":
            self._update_nickname(faces)
        elif self.state == "playing":
            self._update_playing(dt, faces)
        elif self.state == "game_over":
            self._update_game_over(faces)

    def _update_leaderboard(self, faces: list[FaceState]) -> None:
        mode = _mode_from_palms(self.camera.open_palms)
        if mode is not None:
            if self.mode_candidate != mode:
                self.mode_candidate = mode
                self.start_since = time.monotonic()
                return
            self.start_since = self.start_since or time.monotonic()
            if time.monotonic() - self.start_since > 1.2:
                self.player_count = mode
                self.state = "difficulty"
                self.difficulty_phase = "release"
                self.difficulty_candidate = None
                self.difficulty_since = None
                self.release_since = None
                self.sounds.play("start")
        else:
            self.start_since = None
            self.mode_candidate = None

    def _update_difficulty(self) -> None:
        if self.difficulty_phase == "release":
            hands_released = self.camera.open_palms == 0 and self.camera.fingers_up == 0
            if hands_released:
                self.release_since = self.release_since or time.monotonic()
                if time.monotonic() - self.release_since > DIFFICULTY_RELEASE_SECONDS:
                    self.difficulty_phase = "choose"
                    self.difficulty_candidate = None
                    self.difficulty_since = None
                    self.sounds.play("click")
            else:
                self.release_since = None
            return

        level = int(_clamp(self.camera.fingers_up, 0, 4))
        if level <= 0:
            self.difficulty_candidate = None
            self.difficulty_since = None
            return

        if self.difficulty_candidate != level:
            self.difficulty_candidate = level
            self.difficulty_since = time.monotonic()
            return

        if self.difficulty_since and time.monotonic() - self.difficulty_since > DIFFICULTY_CONFIRM_SECONDS:
            self.difficulty_level = level
            self.pads = [NicknamePad(f"PLAYER {index + 1}") for index in range(self.player_count)]
            self.nickname_index = 0
            self.pointer_pos = (WIDTH // 2, HEIGHT // 2)
            self.state = "nickname"
            self.sounds.play("done")

    def _update_nickname(self, faces: list[FaceState]) -> None:
        if self.nickname_index >= len(self.pads):
            return

        active_pad = self.pads[self.nickname_index]
        face = faces[self.nickname_index] if len(faces) > self.nickname_index else (faces[0] if faces else None)
        if face is not None:
            self.pointer_pos = _pointer_from_face(face)
            key = _key_at(self.pointer_pos)
            if key is not None:
                active_pad.focus = KEYS.index(key)
            if face.mouth_event:
                active_pad.press(key)
                self.sounds.play("click")
                if active_pad.done:
                    self.nickname_index += 1
                    self.sounds.play("done")

        if all(pad.done for pad in self.pads):
            nicknames = tuple(pad.nickname for pad in self.pads)
            self.game = MathGame(nicknames, difficulty_level=self.difficulty_level)
            self.saved_scores = False
            self.state = "playing"

    def _update_playing(self, dt: float, faces: list[FaceState]) -> None:
        if self.game is None:
            return

        for index, face in enumerate(faces[:2]):
            if index >= len(self.game.players):
                continue
            if len(self.game.players) == 1:
                self.game.players[index].basket_x = _clamp(face.x, 0.05, 0.95)
            else:
                self.game.players[index].basket_x = _normalized_player_x(index, face.x)

        self.game.update(dt)
        for event in self.game.events:
            self.sounds.play(event)
        self.game.events.clear()
        if self.game.finished:
            self._save_scores_once()
            self.sounds.play("danger" if self.game.finish_reason == "division_by_zero" else "done")
            self.start_since = None
            self.state = "game_over"

    def _update_game_over(self, faces: list[FaceState]) -> None:
        if self.camera is None:
            return
        if self.camera.open_palms >= 2:
            self.start_since = self.start_since or time.monotonic()
            if time.monotonic() - self.start_since > 1.2:
                self._return_to_leaderboard()
        else:
            self.start_since = None

    def _return_to_leaderboard(self) -> None:
        self.state = "leaderboard"
        self.game = None
        self.start_since = None
        self.mode_candidate = None

    def _save_scores_once(self) -> None:
        if self.saved_scores or self.game is None:
            return
        for player in self.game.players:
            self.leaderboard.add_score(player.nickname, player.score, eliminated=player.eliminated)
        self.saved_scores = True

    def _draw(self, faces: list[FaceState]) -> None:
        self._draw_camera_background()
        if self.state == "camera_select":
            self._draw_camera_select()
        elif self.state == "leaderboard":
            self._draw_leaderboard(faces)
        elif self.state == "nickname":
            self._draw_nickname()
        elif self.state == "difficulty":
            self._draw_difficulty()
        elif self.state == "playing":
            self._draw_playing()
        elif self.state == "game_over":
            self._draw_game_over()

    def _draw_camera_background(self) -> None:
        frame = self.camera.last_frame_rgb if self.camera is not None else None
        self.screen.fill(BG)
        if frame is None:
            return
        height, width = frame.shape[:2]
        surface = pygame.image.frombuffer(frame.tobytes(), (width, height), "RGB")
        surface = pygame.transform.smoothscale(surface, (WIDTH, HEIGHT))
        self.screen.blit(surface, (0, 0))
        veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        veil.fill((6, 10, 14, 178))
        self.screen.blit(veil, (0, 0))

    def _draw_camera_select(self) -> None:
        self._draw_logo((WIDTH - 210, 42), max_width=150, max_height=92)
        _text(self.screen, self.big, "MathFalls", (80, 58), TEXT)
        _text(self.screen, self.font, "Selecciona la camara", (86, 140), YELLOW)
        _text(self.screen, self.small, "Click sobre una opcion o usa flechas y Enter", (88, 184), MUTED)

        total = len(self.available_cameras)
        for index, camera_index in enumerate(self.available_cameras):
            rect = _camera_button_rect(index, total)
            active = camera_index == self.selected_camera
            pygame.draw.rect(self.screen, BLUE if active else PANEL, rect, border_radius=8)
            pygame.draw.rect(self.screen, TEXT if active else MUTED, rect, width=2, border_radius=8)
            title = self.mid.render(f"Camara {camera_index}", True, INK if active else TEXT)
            self.screen.blit(title, title.get_rect(center=(rect.centerx, rect.centery - 12)))
            caption = self.small.render("seleccionada" if active else "disponible", True, INK if active else MUTED)
            self.screen.blit(caption, caption.get_rect(center=(rect.centerx, rect.centery + 32)))

    def _draw_leaderboard(self, faces: list[FaceState]) -> None:
        self._draw_logo((WIDTH - 210, 42), max_width=150, max_height=92)
        _text(self.screen, self.big, "MathFalls", (80, 56), TEXT)
        _text(self.screen, self.font, "Top 10", (86, 128), YELLOW)

        rows = self.leaderboard.top(10)
        if not rows:
            _text(self.screen, self.font, "Sin puntajes todavia", (86, 206), MUTED)
        for index, row in enumerate(rows):
            y = 194 + index * 42
            _text(self.screen, self.font, f"{index + 1:02d}", (90, y), MUTED)
            _text(self.screen, self.font, row.nickname, (160, y), TEXT)
            _text(self.screen, self.font, _score(row.score), (470, y), GREEN)
            if row.eliminated:
                _text(self.screen, self.small, "/ 0", (560, y + 5), RED)

        box = pygame.Rect(760, 120, 420, 360)
        pygame.draw.rect(self.screen, PANEL, box, border_radius=8)
        pygame.draw.rect(self.screen, BLUE if self.camera.open_palms >= 2 else MUTED, box, width=3, border_radius=8)
        _text(self.screen, self.mid, f"{self.camera.open_palms}", (955, 196), TEXT)
        _text(self.screen, self.font, "palmas abiertas", (850, 286), MUTED)
        _text(self.screen, self.small, "2 palmas: solitario", (854, 332), TEXT)
        _text(self.screen, self.small, "4 palmas: competencia", (840, 360), TEXT)
        _text(self.screen, self.small, f"detector: {self.camera._hands_backend}", (890, 386), MUTED)

    def _draw_difficulty(self) -> None:
        self._draw_logo((WIDTH - 210, 42), max_width=150, max_height=92)
        mode = "Solitario" if self.player_count == 1 else "Competencia"
        _text(self.screen, self.big, mode, (80, 58), TEXT)
        _text(self.screen, self.font, "Seleccion de dificultad", (86, 136), YELLOW)
        if self.difficulty_phase == "release":
            _text(self.screen, self.font, "Baja las manos para continuar", (86, 186), TEXT)
        else:
            _text(self.screen, self.font, "Levanta de 1 a 4 dedos y mantenlos", (86, 186), TEXT)

        level = 0 if self.difficulty_phase == "release" else int(_clamp(self.camera.fingers_up, 0, 4))
        for index in range(1, 5):
            x = 120 + (index - 1) * 230
            rect = pygame.Rect(x, 300, 170, 140)
            active = level == index
            color = GREEN if active else PANEL
            pygame.draw.rect(self.screen, color, rect, border_radius=8)
            pygame.draw.rect(self.screen, TEXT if active else MUTED, rect, width=2, border_radius=8)
            label = self.big.render(str(index), True, INK if active else TEXT)
            self.screen.blit(label, label.get_rect(center=(rect.centerx, rect.centery - 12)))
            caption = self.small.render("actual" if index == 4 else "facil" if index == 1 else "medio", True, INK if active else MUTED)
            self.screen.blit(caption, caption.get_rect(center=(rect.centerx, rect.bottom - 28)))

        if self.difficulty_phase == "release":
            _text(self.screen, self.font, f"manos detectadas: {self.camera.open_palms}", (86, 530), MUTED)
        else:
            _text(self.screen, self.font, f"detectado: {level}/4", (86, 530), BLUE if level else MUTED)
            if level:
                held = 0 if self.difficulty_candidate != level or self.difficulty_since is None else time.monotonic() - self.difficulty_since
                progress = _clamp(held / DIFFICULTY_CONFIRM_SECONDS, 0.0, 1.0)
                pygame.draw.rect(self.screen, PANEL, pygame.Rect(86, 580, 360, 16), border_radius=8)
                pygame.draw.rect(self.screen, GREEN, pygame.Rect(86, 580, int(360 * progress), 16), border_radius=8)

    def _draw_nickname(self) -> None:
        self._draw_logo((WIDTH - 190, 34), max_width=130, max_height=76)
        active = min(self.nickname_index, len(self.pads) - 1)
        pad = self.pads[active]
        accent = BLUE if active == 0 else GREEN
        _text(self.screen, self.mid, f"Nickname {active + 1}", (70, 36), TEXT)
        area = pygame.Rect(0, 98, WIDTH, HEIGHT - 98)
        self._draw_pad(area, pad, accent)
        self._draw_nickname_progress(active)
        self._draw_pointer(accent)

    def _draw_pad(self, area: pygame.Rect, pad: NicknamePad, accent: tuple[int, int, int]) -> None:
        left = area.left + 140
        _text(self.screen, self.font, pad.label, (left, area.top + 12), accent)
        name_rect = pygame.Rect(left, area.top + 56, area.width - 280, 54)
        pygame.draw.rect(self.screen, PANEL, name_rect, border_radius=8)
        pygame.draw.rect(self.screen, accent, name_rect, width=2, border_radius=8)
        _text(self.screen, self.mid, pad.nickname if pad.name else "_", (name_rect.x + 16, name_rect.y + 7), TEXT)

        cols = 8
        gap = 8
        cell_w = (area.width - 280 - gap * (cols - 1)) // cols
        cell_h = 52
        start_y = area.top + 148
        for i, key in enumerate(KEYS):
            row = i // cols
            col = i % cols
            rect = pygame.Rect(left + col * (cell_w + gap), start_y + row * (cell_h + gap), cell_w, cell_h)
            active = i == pad.focus and not pad.done
            fill = accent if active else PANEL_2
            pygame.draw.rect(self.screen, fill, rect, border_radius=8)
            if active:
                pygame.draw.rect(self.screen, TEXT, rect, width=2, border_radius=8)
            color = INK if active else TEXT
            label = self.font.render(key, True, color)
            self.screen.blit(label, label.get_rect(center=rect.center))

        if pad.done:
            done = pygame.Rect(left, area.bottom - 82, area.width - 280, 48)
            pygame.draw.rect(self.screen, GREEN, done, border_radius=8)
            label = self.font.render("LISTO", True, INK)
            self.screen.blit(label, label.get_rect(center=done.center))

    def _draw_nickname_progress(self, active: int) -> None:
        for index, pad in enumerate(self.pads):
            x = 940 + index * 130
            color = GREEN if pad.done else (BLUE if index == active else MUTED)
            rect = pygame.Rect(x, 44, 98, 34)
            pygame.draw.rect(self.screen, color, rect, border_radius=8)
            label = self.small.render(f"P{index + 1}", True, INK)
            self.screen.blit(label, label.get_rect(center=rect.center))

    def _draw_pointer(self, accent: tuple[int, int, int]) -> None:
        x, y = self.pointer_pos
        pygame.draw.circle(self.screen, accent, (x, y), 18)
        pygame.draw.circle(self.screen, TEXT, (x, y), 18, width=3)
        pygame.draw.line(self.screen, TEXT, (x - 26, y), (x + 26, y), 2)
        pygame.draw.line(self.screen, TEXT, (x, y - 26), (x, y + 26), 2)

    def _draw_playing(self) -> None:
        if self.game is None:
            return
        self._draw_logo((WIDTH - 138, 22), max_width=96, max_height=54)
        _text(self.screen, self.mid, f"{int(self.game.remaining):02d}", (WIDTH // 2 - 28, 20), YELLOW)
        _text(self.screen, self.small, f"nivel {self.game.difficulty_level} x{self.game.difficulty:.2f}", (WIDTH // 2 - 52, 70), MUTED)
        if len(self.game.players) > 1:
            pygame.draw.line(self.screen, MUTED, (WIDTH // 2, 0), (WIDTH // 2, HEIGHT), 2)
        for index, player in enumerate(self.game.players):
            area = _player_area(index, len(self.game.players))
            self._draw_player_game(area, player, BLUE if index == 0 else GREEN)

    def _draw_player_game(self, area: pygame.Rect, player: PlayerGame, accent: tuple[int, int, int]) -> None:
        _text(self.screen, self.font, player.nickname, (area.left + 36, 22), accent)
        _text(self.screen, self.mid, _score(player.score), (area.left + 36, 58), TEXT)

        if player.eliminated:
            overlay = pygame.Surface((area.width, area.height), pygame.SRCALPHA)
            overlay.fill((120, 20, 24, 170))
            self.screen.blit(overlay, area)
            _text(self.screen, self.mid, "ELIMINADO", (area.left + 190, area.centery - 20), TEXT)
            return

        for token in player.tokens:
            x = area.left + int(token.x * area.width)
            y = int(token.y * area.height)
            color = RED if token.operator == "/" and token.operand == 0 else YELLOW
            rect = pygame.Rect(0, 0, 86, 48)
            rect.center = (x, y)
            pygame.draw.rect(self.screen, PANEL_2, rect, border_radius=8)
            pygame.draw.rect(self.screen, color, rect, width=2, border_radius=8)
            label = self.font.render(token.label, True, color)
            self.screen.blit(label, label.get_rect(center=(x, y - 1)))

        basket_w = 120
        bx = area.left + int(player.basket_x * area.width)
        rect = pygame.Rect(0, 0, basket_w, 28)
        rect.center = (bx, int(HEIGHT * 0.9))
        pygame.draw.rect(self.screen, accent, rect, border_radius=8)
        pygame.draw.rect(self.screen, TEXT, rect, width=2, border_radius=8)

    def _draw_game_over(self) -> None:
        if self.game is None:
            return
        self._draw_logo((WIDTH - 250, 62), max_width=180, max_height=110)
        players = self.game.players
        winner = self.game.winner
        _text(self.screen, self.big, "Resultado", (80, 74), TEXT)
        title = f"Gana {winner.nickname}" if len(players) > 1 else winner.nickname
        _text(self.screen, self.mid, title, (84, 150), GREEN)
        if self.game.finish_reason == "division_by_zero":
            _text(self.screen, self.font, "La partida termino por / 0", (86, 202), RED)

        for index, player in enumerate(players):
            y = 250 + index * 90
            _text(self.screen, self.font, player.nickname, (120, y), BLUE if index == 0 else GREEN)
            _text(self.screen, self.mid, _score(player.score), (420, y - 10), TEXT)
            if player.eliminated:
                _text(self.screen, self.font, "ELIMINADO", (560, y), RED)

        _text(self.screen, self.font, "Foto lista", (84, 520), YELLOW)
        _text(self.screen, self.small, "Para volver al Top 10: 2 palmas abiertas o Espacio", (86, 560), TEXT)

    def _draw_logo(self, pos: tuple[int, int], max_width: int, max_height: int) -> None:
        if self.logo is None:
            return
        width, height = self.logo.get_size()
        scale = min(max_width / width, max_height / height, 1.0)
        size = (max(1, int(width * scale)), max(1, int(height * scale)))
        logo = pygame.transform.smoothscale(self.logo, size)
        plate = pygame.Rect(pos[0] - 12, pos[1] - 10, size[0] + 24, size[1] + 20)
        shadow = pygame.Surface((plate.width + 8, plate.height + 8), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 95), shadow.get_rect(), border_radius=12)
        self.screen.blit(shadow, (plate.x + 4, plate.y + 4))

        backing = pygame.Surface((plate.width, plate.height), pygame.SRCALPHA)
        pygame.draw.rect(backing, (7, 12, 16, 218), backing.get_rect(), border_radius=12)
        pygame.draw.rect(backing, (245, 248, 250, 190), backing.get_rect(), width=2, border_radius=12)
        self.screen.blit(backing, plate.topleft)
        self.screen.blit(logo, pos)


def _normalized_player_x(index: int, face_x: float) -> float:
    if index == 0:
        return _clamp((face_x - 0.05) / 0.50, 0.05, 0.95)
    return _clamp((face_x - 0.45) / 0.50, 0.05, 0.95)


def _mode_from_palms(open_palms: int) -> int | None:
    if open_palms >= 4:
        return 2
    if open_palms >= 2:
        return 1
    return None


def _player_area(index: int, total_players: int) -> pygame.Rect:
    if total_players == 1:
        return pygame.Rect(0, 0, WIDTH, HEIGHT)
    return pygame.Rect(index * WIDTH // 2, 0, WIDTH // 2, HEIGHT)


def _camera_button_rect(index: int, total: int) -> pygame.Rect:
    width = 260
    height = 130
    gap = 28
    total_width = total * width + max(0, total - 1) * gap
    start_x = (WIDTH - total_width) // 2
    return pygame.Rect(start_x + index * (width + gap), 300, width, height)


def _pointer_from_face(face: FaceState) -> tuple[int, int]:
    x = int(_clamp(face.x, 0.02, 0.98) * WIDTH)
    y = int(_clamp((face.y - 0.18) / 0.54, 0.02, 0.98) * HEIGHT)
    return x, y


def _key_at(pos: tuple[int, int]) -> str | None:
    x, y = pos
    left = 140
    top = 98
    cols = 8
    gap = 8
    cell_w = (WIDTH - 280 - gap * (cols - 1)) // cols
    cell_h = 52
    start_y = top + 148
    for index, key in enumerate(KEYS):
        row = index // cols
        col = index % cols
        rect = pygame.Rect(left + col * (cell_w + gap), start_y + row * (cell_h + gap), cell_w, cell_h)
        if rect.collidepoint(x, y):
            return key
    return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _score(value: float) -> str:
    if abs(value - int(value)) < 0.001:
        return str(int(value))
    return f"{value:.2f}"


def _leaderboard_path() -> Path:
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"No se pudo usar {DB_PATH.parent}; usando leaderboard local: {exc}")
        return Path("leaderboard.sqlite3")

    local_db = Path("leaderboard.sqlite3")
    if local_db.exists() and not DB_PATH.exists():
        try:
            shutil.copy2(local_db, DB_PATH)
        except OSError as exc:
            print(f"No se pudo migrar leaderboard local: {exc}")
    return DB_PATH


def _asset_path(relative: str) -> Path:
    packaged_root = getattr(sys, "_MEIPASS", None)
    if packaged_root:
        candidate = Path(packaged_root) / "mathfalls" / "assets" / relative
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parent / "assets" / relative


def _load_logo() -> pygame.Surface | None:
    for filename in ("logo.svg", "logo.png"):
        logo_path = _asset_path(filename)
        if not logo_path.exists():
            continue
        try:
            return pygame.image.load(str(logo_path)).convert_alpha()
        except pygame.error as exc:
            print(f"No se pudo cargar {filename}: {exc}")
    return None


def _text(
    surface: pygame.Surface,
    font: pygame.font.Font,
    value: str,
    pos: tuple[int, int],
    color: tuple[int, int, int],
) -> None:
    surface.blit(font.render(value, True, color), pos)


def _tone(frequency: int, duration: float, volume: float) -> pygame.mixer.Sound:
    sample_rate = 44100
    count = int(sample_rate * duration)
    samples = array("h")
    amplitude = int(32767 * volume)
    fade = max(1, int(sample_rate * 0.01))
    for index in range(count):
        envelope = 1.0
        if index < fade:
            envelope = index / fade
        elif count - index < fade:
            envelope = (count - index) / fade
        value = int(amplitude * envelope * math.sin(2 * math.pi * frequency * index / sample_rate))
        samples.append(value)
    return pygame.mixer.Sound(buffer=samples.tobytes())


def main() -> None:
    try:
        MathFallsApp().run()
    except Exception as exc:
        pygame.quit()
        print(f"MathFalls no pudo iniciar: {exc}", file=sys.stderr)
        raise
