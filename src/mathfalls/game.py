from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


OPERATORS = ["+", "-", "*", "/", "sqrt"]


@dataclass
class FallingToken:
    x: float
    y: float
    speed: float
    operator: str
    operand: int

    @property
    def label(self) -> str:
        if self.operator == "sqrt":
            return f"sqrt {self.operand}"
        return f"{self.operator} {self.operand}"


@dataclass
class PlayerGame:
    nickname: str
    score: float = 0.0
    basket_x: float = 0.5
    tokens: list[FallingToken] = field(default_factory=list)
    spawn_timer: float = 0.0
    eliminated: bool = False


DIFFICULTY_FACTORS = {
    1: 0.45,
    2: 0.62,
    3: 0.80,
    4: 1.00,
}


class MathGame:
    def __init__(self, nicknames: tuple[str, ...], duration: float = 60.0, difficulty_level: int = 4) -> None:
        self.duration = duration
        self.remaining = duration
        self.players = [PlayerGame(nickname) for nickname in nicknames]
        self.difficulty_level = max(1, min(4, difficulty_level))
        self.finished = False
        self.finish_reason = ""
        self.events: list[str] = []

    def update(self, dt: float) -> None:
        if self.finished:
            return
        self.remaining = max(0.0, self.remaining - dt)
        for index, player in enumerate(self.players):
            self._update_player(index, player, dt)
        if self.remaining <= 0:
            self.finished = True
            self.finish_reason = "time"

    def _update_player(self, index: int, player: PlayerGame, dt: float) -> None:
        if player.eliminated:
            return

        player.spawn_timer -= dt
        if player.spawn_timer <= 0:
            player.tokens.append(_make_token(self.difficulty))
            player.spawn_timer = random.uniform(0.42, 0.86) / self.difficulty

        for token in player.tokens:
            token.y += token.speed * dt

        caught: list[FallingToken] = []
        missed: list[FallingToken] = []
        for token in player.tokens:
            if token.y >= 0.86 and abs(token.x - player.basket_x) < 0.11:
                caught.append(token)
            elif token.y >= 1.08:
                missed.append(token)

        for token in caught:
            self.apply_token(player, token)
            self.events.append("danger" if token.operator == "/" and token.operand == 0 else "catch")

        for token in missed:
            self.send_to_other_player(index, token)

        player.tokens = [token for token in player.tokens if token not in caught and token not in missed]

    def apply_token(self, player: PlayerGame, token: FallingToken) -> None:
        if token.operator == "/" and token.operand == 0:
            player.eliminated = True
            self.finished = True
            self.finish_reason = "division_by_zero"
            return

        number = token.operand
        op = token.operator
        if op == "+":
            player.score += number
        elif op == "-":
            player.score -= number
        elif op == "*":
            player.score *= number
        elif op == "/":
            player.score = round(player.score / number, 2)
        elif op == "sqrt":
            player.score += round(math.sqrt(number), 2)

    def send_to_other_player(self, source_index: int, token: FallingToken) -> None:
        if len(self.players) < 2:
            return
        target_index = 1 - source_index
        target = self.players[target_index]
        if target.eliminated:
            return
        token.y = -0.08
        token.x = 1.0 - token.x
        token.speed = min(token.speed * 1.08, 0.72)
        target.tokens.append(token)

    @property
    def difficulty(self) -> float:
        elapsed = self.duration - self.remaining
        progression = 1.0 + min(elapsed // 15, 3) * 0.22
        return progression * DIFFICULTY_FACTORS[self.difficulty_level]

    @property
    def winner(self) -> PlayerGame:
        active = [player for player in self.players if not player.eliminated]
        if len(active) == 1:
            return active[0]
        return max(self.players, key=lambda item: item.score)


def _make_token(difficulty: float = 1.0) -> FallingToken:
    operator = _choose_operator()
    operand = _choose_operand(operator)
    return FallingToken(
        x=random.uniform(0.12, 0.88),
        y=-0.08,
        speed=random.uniform(0.20, 0.34) * difficulty,
        operator=operator,
        operand=operand,
    )


def _choose_operator() -> str:
    roll = random.random()
    if roll < 0.48:
        return "+"
    if roll < 0.66:
        return "-"
    if roll < 0.84:
        return "*"
    if roll < 0.96:
        return "/"
    return "sqrt"


def _choose_operand(operator: str) -> int:
    if operator == "*":
        return random.choice([0, 1, 2, 2, 3, 4])
    if operator == "/":
        return 0 if random.random() < 0.08 else random.randint(1, 6)
    if operator == "sqrt":
        return random.choice([0, 1, 4, 9, 16, 25, 36, 49, 64, 81])
    return random.randint(0, 9)
