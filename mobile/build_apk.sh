#!/usr/bin/env bash
# Image Studio Android APK 빌드 (sudo/docker 불필요)
#
# 앱은 imggen.ai-ve.uk 를 로드하는 **WebView 셸**이다 — 화면·기능은 전부 서버의 웹에서 오므로
# 웹을 고치면 앱을 다시 빌드할 필요가 없다. 이 스크립트는 셸(껍데기) 자체가 바뀔 때만 돌리면 된다.
#
# 방식: aarch64 호스트에서 JDK17·Gradle 은 네이티브로 돌리고, x86_64 전용인 aapt2 만
# qemu-user-static 으로 에뮬레이션한다(~/android-build/native/ 에 준비돼 있음).
#
# 사용법:
#   ./build_apk.sh                          # debug APK 빌드
#   IMGGEN_DRIVE_UPLOAD=1 ./build_apk.sh  # 빌드 후 Google Drive(apk/) 업로드
#
# 산출물: ./ImageStudio.apk
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NATIVE="${HOME}/android-build/native"
APK_OUT="${HERE}/ImageStudio.apk"

log(){ printf '\033[1;36m[imggen-apk]\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[imggen-apk] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ -x "${NATIVE}/aapt2-wrap/aapt2" ] || die "네이티브 빌드 툴체인 없음: ${NATIVE} (jdk17/sdk/aapt2-wrap)"

export JAVA_HOME="${NATIVE}/jdk17"
export ANDROID_HOME="${NATIVE}/sdk"
cd "$HERE"
echo "sdk.dir=${ANDROID_HOME}" > local.properties

log "gradlew assembleDebug…"
# AGP 는 오버라이드 경로의 파일명이 정확히 'aapt2' 여야 받아들인다 (aapt2-wrap/aapt2)
./gradlew --no-daemon assembleDebug \
  -Pandroid.aapt2FromMavenOverride="${NATIVE}/aapt2-wrap/aapt2"

APK_SRC="app/build/outputs/apk/debug/app-debug.apk"
[ -f "$APK_SRC" ] || die "APK 미생성: $APK_SRC"
cp -f "$APK_SRC" "$APK_OUT"
log "완료: $(ls -lh "$APK_OUT" | awk '{print $9, "("$5")"}')"

if [ "${IMGGEN_DRIVE_UPLOAD:-0}" = "1" ]; then
  log "Google Drive 업로드 (apk/ImageStudio.apk)…"
  rclone copyto "$APK_OUT" "gdrive:apk/ImageStudio.apk" --progress \
    || log "⚠ Drive 업로드 실패 — 빌드 자체는 정상."
fi
