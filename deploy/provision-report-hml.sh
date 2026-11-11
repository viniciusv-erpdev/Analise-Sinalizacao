#!/usr/bin/env bash
# PREPARED ONLY. No invocation is part of stage 5B. Dedicated disposable VM ONLY.
# Installs inert files/accounts/directories; NEVER starts/enables a unit, reloads
# systemd, connects to a database, applies migrations, or enables publication.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077
if [[ $# != 2 || "$1" != --disposable-host-approved ]]; then
  echo 'Usage: provision-report-hml.sh --disposable-host-approved /opt/analise-launcher/<version>/.venv' >&2
  exit 2
fi
[[ $(id -u) == 0 ]] || { echo 'Root required for future isolated provisioning' >&2; exit 1; }
sentinel=/etc/analise-hml-disposable
[[ -f "$sentinel" && ! -L "$sentinel" && $(stat -c %u "$sentinel") == 0 &&
   $(stat -c %a "$sentinel") == 600 && $(cat "$sentinel") == ANALISE_REPORT_HML_ONLY ]] || {
  echo 'Missing separately approved disposable-host sentinel' >&2; exit 1;
}
launcher_venv=$2
[[ "$launcher_venv" =~ ^/opt/analise-launcher/[a-zA-Z0-9._-]+/\.venv$ && -x "$launcher_venv/bin/python" ]] || {
  echo 'A separately installed root-owned standalone launcher venv is required' >&2; exit 1;
}
for parent in /opt /opt/analise-launcher "$(dirname -- "$launcher_venv")" "$launcher_venv"; do
  [[ -d "$parent" && ! -L "$parent" && $(stat -c %u "$parent") == 0 ]] || exit 1
  [[ -z $(find -P "$parent" -maxdepth 0 -perm /022 -print) ]] || exit 1
done
[[ -z $(find -P "$launcher_venv" \( -type l -o ! -user root -o -perm /022 \) -print -quit) ]] || {
  echo 'Launcher environment contains links or untrusted ownership/modes' >&2; exit 1;
}
"$launcher_venv/bin/python" -I -B -c 'import importlib.util; assert all(importlib.util.find_spec(n) is None for n in ("django", "signaling", "config"))'
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Fail before mutations if this could touch an existing installation or account.
for account in analise_app analise_dispatch; do
  if getent passwd "$account" >/dev/null || getent group "$account" >/dev/null; then
    echo 'Existing account/group: inspect manually; never reuse production identities' >&2; exit 1
  fi
done
for target in /etc/analise-report-launcher /etc/analise-hml /var/lib/analise-hml \
  /run/analise-report-launcher /etc/tmpfiles.d/analise-report-hml.conf \
  /etc/systemd/system/report-launcher.service /etc/systemd/system/report-launcher.socket; do
  [[ ! -e "$target" && ! -L "$target" ]] || { echo "Target already exists: $target" >&2; exit 1; }
done
for template in report-launcher.service.example report-launcher.socket.example report-launcher-catalog.json.example; do
  [[ -f "$source_dir/$template" ]] || { echo 'Missing reviewed template' >&2; exit 1; }
done
useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin analise_app
useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin analise_dispatch
install -d -o root -g root -m 0700 /etc/analise-report-launcher /etc/analise-hml
install -d -o root -g root -m 0755 /var/lib/analise-hml
install -d -o analise_app -g analise_app -m 0700 /var/lib/analise-hml/reports
install -d -o root -g analise_dispatch -m 0750 /run/analise-report-launcher
printf 'd /run/analise-report-launcher 0750 root analise_dispatch -\n' > /etc/tmpfiles.d/analise-report-hml.conf
chmod 0644 /etc/tmpfiles.d/analise-report-hml.conf
sed -e "s|<LAUNCHER_VENV>|$launcher_venv|g" \
    -e 's|<PRIVATE_REPORT_ROOT>|/var/lib/analise-hml/reports|g' \
    "$source_dir/report-launcher.service.example" > /etc/systemd/system/report-launcher.service
install -o root -g root -m 0644 "$source_dir/report-launcher.socket.example" /etc/systemd/system/report-launcher.socket
chmod 0644 /etc/systemd/system/report-launcher.service
sed -e "s/99999/$(id -u analise_dispatch)/" \
    -e 's|/var/lib/analise/reports|/var/lib/analise-hml/reports|' \
    "$source_dir/report-launcher-catalog.json.example" > /etc/analise-report-launcher/catalog.json
# Deliberately unusable until a separate approved credential/configuration step.
: > /etc/analise-report-launcher/database.dsn
printf 'REPORT_DISPATCH_ENABLED=false\nREPORT_DISPATCH_DSN=\nREPORT_EXECUTOR_RELEASE_ID=\n' > /etc/analise-hml/dispatcher.env
printf 'REPORT_EXECUTOR_ENABLED=false\nREPORT_SYSTEMD_SUPERVISION_ENABLED=false\n' > /etc/analise-hml/executor.env
printf 'REPORT_FINALIZATION_ENABLED=false\nREPORT_ASYNC_PUBLICATION_ENABLED=false\nREPORT_ADMISSION_ENABLED=false\n' > /etc/analise-hml/http.env
chmod 0600 /etc/analise-report-launcher/catalog.json /etc/analise-report-launcher/database.dsn /etc/analise-hml/*.env
echo 'Inert preparation complete. No units loaded/started/enabled. No database or CD touched.'
echo 'If interrupted, preserve partial state and inspect; no automatic rollback or overwrite.'
