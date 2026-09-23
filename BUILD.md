# Сборка debforge после клонирования

Вся сборка выполняется внутри одного контейнера. На хосте не запускаются
`debforge`, `uv`, APT или `dpkg-buildpackage`, и контейнер не обращается к
Docker API.

## 1. Требования к машине

Обязательны только Git и Docker:

```sh
git --version
docker version
docker run --rm debian:12.0 true
```

GPG на хосте нужен только для экспорта существующего ключа. Если два файла
секретов уже подготовлены на другой машине, устанавливать GPG не требуется.

Для полной выборки пакетов желательно иметь не менее 40–50 ГиБ свободного
места.

## 2. Клонировать проект и собрать образ

```sh
git clone <URL-РЕПОЗИТОРИЯ>
cd debforge
docker build -t debforge-builder:latest -f docker/Dockerfile.builder .
```

Последняя точка обязательна: контекстом Docker build служит корень репозитория.
Образ основан на `debian:12.0` и содержит:

- исходники `debforge`;
- `uv` и виртуальное окружение `/app/.venv`;
- APT и Debian build toolchain;
- `debsigs`, `debsig-verify` и GnuPG.

Проектные Python-зависимости устанавливаются в `/app/.venv` командой
`uv sync --locked --no-dev --inexact` во время сборки образа.

Проверка образа:

```sh
docker run --rm debforge-builder:latest --help
```

## 3. Подготовить список пакетов

На целевом устройстве выполните:

```sh
dpkg-query -W -f='${Package}\t${Version}\n' > pkg.tsv
```

Перенесите `pkg.tsv` в корень проекта. Формат каждой непустой строки:

```text
Package<TAB>Version
```

Имена и версии используются без неявного обновления до более свежей версии.

## 4. Подготовить ключ подписи

Создайте локальный каталог, который уже исключён из Git и Docker build context:

```sh
mkdir -p secrets
chmod 0700 secrets
```

Экспортируйте приватный ключ:

```sh
gpg --armor --export-secret-keys <FINGERPRINT> \
  > secrets/debforge-gpg-private-key
```

Создайте файл `secrets/debforge-gpg-passphrase`, содержащий только пароль от
ключа, затем ограничьте доступ:

```sh
chmod 0400 \
  secrets/debforge-gpg-private-key \
  secrets/debforge-gpg-passphrase
```

Подпись обязательна. Оба файла монтируются read-only непосредственно в
`/run/secrets` контейнера. Содержимое ключа и пароль не передаются через CLI,
YAML или переменные окружения.

## 5. Проверить первые три пакета

Перед полной сборкой удобно выполнить smoke-тест:

```sh
head -n 3 pkg.tsv > pkg-smoke.tsv
mkdir -p artifacts-smoke .debforge-work-smoke

docker run --rm --init \
  --mount type=bind,src="$PWD/pkg-smoke.tsv",dst=/input/pkg.tsv,readonly \
  --mount type=bind,src="$PWD/artifacts-smoke",dst=/output \
  --mount type=bind,src="$PWD/.debforge-work-smoke",dst=/work \
  --mount type=bind,src="$PWD/secrets/debforge-gpg-private-key",dst=/run/secrets/debforge-gpg-private-key,readonly \
  --mount type=bind,src="$PWD/secrets/debforge-gpg-passphrase",dst=/run/secrets/debforge-gpg-passphrase,readonly \
  debforge-builder:latest \
  -c /app/debforge.bookworm.yaml \
  build --packages-file /input/pkg.tsv
```

В проверенном нативном ARM64-запуске первые три пакета из текущего `pkg.tsv`
дали следующие результаты:

```text
acl      2.3.1-3  arm64
adduser  3.134    all
apt      2.6.1    arm64
```

Все три `.deb` были подписаны `debsigs` подписью типа `origin` и успешно
проверены `debsig-verify`.

Проверить метаданные и наличие встроенной подписи можно тем же образом внутри
образа:

```sh
docker run --rm --entrypoint sh \
  --mount type=bind,src="$PWD/artifacts-smoke",dst=/artifacts,readonly \
  debforge-builder:latest -c '
    for package in /artifacts/*.deb; do
      dpkg-deb -f "$package" Package Version Architecture
      debsigs --list "$package"
    done
  '
```

Итог каждого запуска записывается в `artifacts-smoke/build-manifest.json`.
Успешная подпись имеет `signing.signed: true`, а каждый элемент
`signing.artifacts` — `verified: true`.

## 6. Собрать весь список нативно

```sh
mkdir -p artifacts .debforge-work

docker run --rm --init \
  --mount type=bind,src="$PWD/pkg.tsv",dst=/input/pkg.tsv,readonly \
  --mount type=bind,src="$PWD/artifacts",dst=/output \
  --mount type=bind,src="$PWD/.debforge-work",dst=/work \
  --mount type=bind,src="$PWD/secrets/debforge-gpg-private-key",dst=/run/secrets/debforge-gpg-private-key,readonly \
  --mount type=bind,src="$PWD/secrets/debforge-gpg-passphrase",dst=/run/secrets/debforge-gpg-passphrase,readonly \
  debforge-builder:latest \
  -c /app/debforge.bookworm.yaml \
  build --packages-file /input/pkg.tsv
```

Подписанные пакеты и `build-manifest.json` появятся в `artifacts/`. Из каждого
source package сохраняются только бинарные пакеты, явно перечисленные во
входном файле.

## 7. Корпоративный APT proxy

Контейнер читает те же переменные, что и `debsec`:

- `DEBSEC_PROXY_TOKEN` включает корпоративный режим;
- `DEBSEC_PROXY_HOST` переопределяет хост, по умолчанию используется
  `proxy.host`.

Чтобы токен не попал в историю shell:

```sh
read -rsp 'Proxy token: ' DEBSEC_PROXY_TOKEN
echo
export DEBSEC_PROXY_TOKEN
export DEBSEC_PROXY_HOST='proxy.host'  # необязательно
```

В команду `docker run` перед именем образа добавьте:

```sh
--env DEBSEC_PROXY_TOKEN \
--env DEBSEC_PROXY_HOST \
```

Токен используется только во временном APT `auth.conf` с правами `0600` и
удаляется после запуска, в том числе с `--keep-artifacts`. В manifest и логи он
не записывается.

Важно: переменные применяются к APT во время запуска рабочего контейнера.
Первичная команда `docker build` отдельно должна иметь доступ к Debian mirror и
PyPI.

## 8. Кросс-сборка ARM64 на x86-64

Добавьте к аргументам команды `build`:

```sh
--architecture arm64
```

Например, окончание команды будет выглядеть так:

```sh
debforge-builder:latest \
  -c /app/debforge.bookworm.yaml \
  build --packages-file /input/pkg.tsv --architecture arm64
```

`debforge` добавит foreign architecture, установит
`crossbuild-essential-arm64`, получит зависимости с
`--host-architecture=arm64` и вызовет `dpkg-buildpackage` с
`--host-arch=arm64`. Поддержка кросс-компиляции всё равно зависит от packaging
конкретного source package.

## 9. Диагностика

Чтобы сохранить исходники и APT sandbox после ошибки, добавьте:

```sh
--keep-artifacts
```

Временный рабочий каталог останется в примонтированном `/work`, но файл с
токеном корпоративного proxy всё равно будет удалён.

Для пересборки образа после изменений проекта повторите:

```sh
docker build -t debforge-builder:latest -f docker/Dockerfile.builder .
```
