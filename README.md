# MathFalls

Juego local para dos jugadores controlado solo por camara.

## MVP incluido

- Pantalla idle con top 10 de puntajes.
- Pantalla previa para elegir la camara desde la interfaz.
- Logo persistente en las pantallas principales si existe `src/mathfalls/assets/logo.svg`.
- Inicio automatico por palmas:
  - 2 palmas abiertas: modo solitario.
  - 4 palmas abiertas: modo competencia.
- Luego del modo, la dificultad se elige levantando dedos:
  - Primero hay que bajar las manos para evitar que las palmas del modo cuenten como dificultad.
  - 1 dedo: mas facil.
  - 4 dedos: dificultad actual/original.
- Teclado virtual por turnos:
  - Primero registra el jugador 1 y luego el jugador 2.
  - Mover la cabeza controla el puntero.
  - Abrir la boca hace click sobre la tecla apuntada.
- La camara se muestra como fondo atenuado detras de la interfaz.
- La imagen de camara se corrige horizontalmente para no verse en espejo.
- Efectos de sonido para clicks, inicio, capturas y fin de partida.
- Partida de 60 segundos con pantalla dividida.
- En solitario la pantalla es completa; en competencia se divide en dos.
- Cada jugador mueve su cesta usando la posicion horizontal de su cabeza.
- Caen operaciones completas como `+ 4`, `* 2`, `/ 5`, `* 0` y `/ 0`.
- Si un jugador atrapa `/ 0`, pierde inmediatamente la partida.
- La dificultad aumenta cada 15 segundos.
- Los objetos que un jugador evita y llegan al margen inferior reaparecen arriba para el otro jugador.
- Ranking persistente en SQLite.
- Al terminar una partida se muestra una pantalla de resultados con la camara de fondo para foto; se vuelve al Top 10 con 2 palmas o Espacio.

## Desarrollo

Ubica el logo del proyecto en:

```bash
src/mathfalls/assets/logo.svg
```

Ese archivo se incluye automaticamente en desarrollo y en los builds de PyInstaller.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python -m mathfalls
```

Tambien puedes usar el comando instalado:

```bash
mathfalls
```

## Produccion

La ruta recomendada para un instalable local es PyInstaller. El mismo proyecto sirve para macOS y Windows, pero el binario debe construirse en el sistema objetivo.

### macOS

```bash
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[build]"
PYINSTALLER_CONFIG_DIR=/tmp/mathfalls-pyinstaller pyinstaller packaging/MathFalls.spec
```

El ejecutable directo quedara en `dist/MathFalls`.

Para generar una app macOS abrible con doble click:

```bash
PYINSTALLER_CONFIG_DIR=/tmp/mathfalls-pyinstaller pyinstaller packaging/MathFallsApp.spec
```

La app quedara en `dist/MathFalls.app`.

Si una app anterior quedo con permisos dificiles de reemplazar, puedes generar en una carpeta alternativa:

```bash
PYINSTALLER_CONFIG_DIR=/tmp/mathfalls-pyinstaller pyinstaller packaging/MathFallsApp.spec --distpath release
pkgbuild --component release/MathFalls.app --install-location /Applications release/MathFalls.pkg
```

Para generar un instalador `.pkg` real desde la app:

```bash
pkgbuild --component dist/MathFalls.app --install-location /Applications dist/MathFalls.pkg
```

El instalador quedara en `dist/MathFalls.pkg`.

Importante: `build/MathFalls/MathFalls.pkg` es un archivo interno de PyInstaller, no un instalador macOS. No debe abrirse con Installer.

### Windows

Desde PowerShell, en una maquina Windows:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e ".[build]"
python -m PyInstaller packaging\MathFalls.spec --noconfirm --clean
```

El ejecutable quedara en `dist\MathFalls.exe`.

Si `python` tampoco se reconoce, instala Python 3.10 o superior desde
https://www.python.org/downloads/windows/ y marca la opcion `Add python.exe to
PATH` durante la instalacion. Despues cierra y vuelve a abrir PowerShell.

Si tienes instalado el Python Launcher, tambien puedes usar este primer comando:

```powershell
py -3 -m venv .venv
```

## Decisiones iniciales

- MediaPipe Face Mesh se usa para detectar caras, ojos y boca.
- Si FaceMesh no puede iniciar por aceleracion grafica/permisos del sistema, el juego cae a deteccion OpenCV Haar para evitar que la app se cierre.
- Para el inicio por palmas se usa MediaPipe Hands; si no esta disponible, se usa un fallback OpenCV por contornos.
- OpenCV se usa para leer la camara a traves de la dependencia que instala MediaPipe.
- Pygame renderiza el juego.
- El ranking se guarda en `~/.mathfalls/leaderboard.sqlite3`.
- Gana el jugador con mayor puntaje individual.
- El puntaje inicia en 0.
- En modo solitario se guarda el puntaje individual al terminar.
- Las operaciones se aplican directamente sobre el puntaje actual.
- `sqrt n` suma la raiz cuadrada de `n` al puntaje.
- `/ 0` elimina al jugador y no guarda su puntaje en el ranking.
