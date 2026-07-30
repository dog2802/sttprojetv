# Переопределяет встроенный контриб-хук PyInstaller для webrtcvad: тот пытается прочитать
# метаданные пакета по имени "webrtcvad", а у нас установлен "webrtcvad-wheels"
# (другое имя дистрибутива с тем же модулем import webrtcvad) - из-за этого сборка падает
# с PackageNotFoundError. Модулю для работы никакие метаданные не нужны, только сам импорт.
hiddenimports = ["webrtcvad"]
