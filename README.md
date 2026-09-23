# debforge

`debforge` пересобирает Debian-пакеты из исходных кодов и подписывает каждый
полученный `.deb` через `debsigs`.

Весь процесс выполняется **в одном контейнере** на базе `debian:12.0`:

- `uv` и проектная среда `/app/.venv` находятся внутри образа;
- `debforge/steps/download.py` создаёт изолированную конфигурацию APT и получает исходники;
- `debforge/steps/build.py` устанавливает build-dependencies и запускает `dpkg-buildpackage`;
- `debforge/steps/sign_package.py` подписывает и проверяет `.deb`;
- `debforge/pipeline.py` связывает эти шаги и создаёт `build-manifest.json`.

Python-код не подключается к Docker API и не запускает другие контейнеры.
Публикации пакетов нет: результат сохраняется в примонтированный каталог `/output`.

## Быстрый запуск

```sh
docker build -t debforge-builder:latest -f docker/Dockerfile.builder .
mkdir -p artifacts .debforge-work

docker run --rm --init \
  --mount type=bind,src="$PWD/pkg.tsv",dst=/input/pkg.tsv,readonly \
  --mount type=bind,src="$PWD/artifacts",dst=/output \
  --mount type=bind,src="$PWD/.debforge-work",dst=/work \
  --mount type=bind,src="$PWD/secrets/debforge-gpg-private-key",dst=/run/secrets/debforge-gpg-private-key,readonly \
  --mount type=bind,src="$PWD/secrets/debforge-gpg-passphrase",dst=/run/secrets/debforge-gpg-passphrase,readonly \
  debforge-builder:latest \
  -c /app/debforge.bookworm.yaml build --packages-file /input/pkg.tsv
```

Формат `pkg.tsv` — точный вывод:

```sh
dpkg-query -W -f='${Package}\t${Version}\n' > pkg.tsv
```

Для кросс-сборки ARM64 на x86-64 добавьте `--architecture arm64`. Нативная
архитектура используется по умолчанию. Подробная инструкция находится в
[`BUILD.md`](BUILD.md).

## Корпоративный APT proxy

Передайте тот же токен, что использует `debsec`:

```sh
docker run --rm --init \
  --env DEBSEC_PROXY_TOKEN \
  --env DEBSEC_PROXY_HOST \
  ... \
  debforge-builder:latest \
  -c /app/debforge.bookworm.yaml build --packages-file /input/pkg.tsv
```

`DEBSEC_PROXY_HOST` необязателен и по умолчанию равен `proxy.host`.
Токен записывается только во временный APT `auth.conf` с правами `0600` и
удаляется после выполнения. В YAML, аргументы команд и manifest он не попадает.

## Подпись

Подпись обязательна. Контейнеру передаются два read-only файла:

- `/run/secrets/debforge-gpg-private-key` — экспортированный приватный GPG-ключ;
- `/run/secrets/debforge-gpg-passphrase` — пароль одной строкой.

Можно выбрать ключ параметром `--gpg-key FINGERPRINT`; иначе используется первый
доступный signing-capable ключ. После `debsigs --sign=origin` каждый пакет
проверяется `debsig-verify`.
