#!/bin/sh
set -eu
cat /etc/os-release
rpm -q python3 python3-pip
python3 --version
python3 -m venv /tmp/venv
export PATH="/tmp/venv/bin:$PATH"
python -m pip install --no-index --no-deps /wheels/tapediag-0.3.0-py3-none-any.whl
python -m pip check
cd /tmp
python /input/scripts/smoke-installed.py
mkdir /tmp/walkthrough
cp -R /input/fixtures /tmp/walkthrough/
cp /input/README.md /tmp/walkthrough/
cd /tmp/walkthrough
sh /input/scripts/mhvtl-quickstart.sh
python /input/scripts/run-readme-quickstart.py
if test -d /out; then
    cp -R artifacts /out/
    rpm -qa --qf '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort > /out/rpm-packages.txt
fi
echo 'Distribution install and verbatim quickstarts: PASS'
