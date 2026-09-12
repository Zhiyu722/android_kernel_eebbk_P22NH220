#!/bin/bash
# ---------------------------------------------------------------------------
# EEBBK S6 (P20H130 / sm6150 / sdmmagpiep) kernel build script
#
#   clang 11 + LLVM lld, Android 10/11 CAF msm-4.14 kernel
#
# Key points
#   1. techpack/audio MUST be built into the kernel image (TECHPACK=y, which is
#      also techpack/Kbuild's own default -- do NOT pass TECHPACK=n).
#      This is what fixes "no sound":
#        * the image then carries the whole QCOM audio stack (Q6/APR, bolero,
#          wcd937x, wsa-macro, aw882xx smart-PA, the sm6150 machine driver);
#        * and, above all, CONFIG_MSM_ADSP_LOADER=y, i.e. techpack/audio/dsp/
#          adsp-loader.c, which binds the "qcom,adsp-loader" DT node and calls
#          subsystem_get("adsp") to bring the ADSP up.  Without it the ADSP
#          never boots, adsprpcd loops on "Transport endpoint is not
#          connected", audioserver never publishes media.audio_policy and the
#          device freezes on the boot animation.
#      The vendor copy of that loader in /vendor/lib/modules cannot do the job
#      here: those modules were built against a different kernel and are ABI
#      incompatible with this tree.
#   2. The link must use ld.lld: the aarch64 GNU ld shipped with modern
#      distributions (2.38) mis-places the .bss.rtic section and fails with
#      "relocation truncated to fit: R_AARCH64_ADR_PREL_PG_HI21".
#
# Usage:
#   ./build_eebbk_clang11.sh                      # factory config + TECHPACK=y
#   TECHPACK_MODE=n ./build_eebbk_clang11.sh      # old, sound-less build
#   CONFIG=h130.config ./build_eebbk_clang11.sh   # build with the repo config
# ---------------------------------------------------------------------------
set -e

TAG=${TAG:-eebbk}
OUT=${OUT:-out}
JOBS=${JOBS:-$(nproc)}
TECHPACK_MODE=${TECHPACK_MODE:-y}
CCBIN=${CCBIN:-clang-11}
LDBIN=${LDBIN:-ld.lld}
KCONFIG=${CONFIG:-h130_factory.config}

cd "$(dirname "$0")"

export ARCH=arm64
export SUBARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-
export CLANG_TRIPLE=aarch64-linux-gnu-
export TARGET_PRODUCT=sm6150
export KBUILD_BUILD_USER=${KBUILD_BUILD_USER:-cp}
export KBUILD_BUILD_HOST=${KBUILD_BUILD_HOST:-ubuntu165}

echo "== toolchain =="
$CCBIN --version | head -1
$LDBIN --version | head -1

# techpack/Kbuild contains "TECHPACK?=y", so leaving this unset also builds the
# audio stack in.  Only an explicit TECHPACK=n removes it (and with it the ADSP
# loader -> no sound at all).
echo "== configure ($KCONFIG, TECHPACK=$TECHPACK_MODE) =="
rm -rf "$OUT"
mkdir -p "$OUT"
cp "arch/arm64/configs/$KCONFIG" "$OUT/.config"
make -j"$JOBS" O="$OUT" CC="$CCBIN" LD="$LDBIN" TECHPACK="$TECHPACK_MODE" olddefconfig

# The vendor DLKM modules in /vendor/lib/modules were signed with the vendor
# module key and carry CRCs computed in the complete vendor tree.  A kernel
# built here cannot match either, so relax just those two checks - the
# vermagic string itself stays identical (that one must match!):
#   * CONFIG_MODULE_SIG_FORCE=n   (keep CONFIG_MODULE_SIG / MODVERSIONS =y)
#   * kernel/module.c check_version() accepts CRC mismatches (see bad_version)
echo "== relax module signature force =="
sed -i 's/^CONFIG_MODULE_SIG_FORCE=y/# CONFIG_MODULE_SIG_FORCE is not set/' "$OUT/.config"
make -j"$JOBS" O="$OUT" CC="$CCBIN" LD="$LDBIN" TECHPACK="$TECHPACK_MODE" olddefconfig
grep -E '^CONFIG_MODVERSIONS|^# CONFIG_MODULE_SIG_FORCE' "$OUT/.config"

echo "== build Image.gz =="
make -j"$JOBS" O="$OUT" CC="$CCBIN" LD="$LDBIN" TECHPACK="$TECHPACK_MODE" DTC=dtc Image.gz

echo "== artifacts =="
ls -la "$OUT/arch/arm64/boot/Image.gz" "$OUT/vmlinux"
echo "kernel release: $(make -s O=$OUT kernelrelease 2>/dev/null || true)"

# ---------------------------------------------------------------------------
# Verify the audio stack really made it into the image.  A correct build shows
# non-zero counts for all of these; the old TECHPACK=n build showed 0 for the
# audio stack and only the camera strings.
# ---------------------------------------------------------------------------
if [ -f "$OUT/arch/arm64/boot/Image.gz" ]; then
  echo "== audio stack inside Image.gz =="
  gzip -dc "$OUT/arch/arm64/boot/Image.gz" > /tmp/_img_check
  for s in adsp-loader q6afe bolero wcd937x wsa wcd_mbhc aw882xx \
           sm6150-wcd9375-snd-card driver/BackCamera_info; do
    printf "  %-28s %s\n" "$s" "$(grep -a -c "$s" /tmp/_img_check)"
  done
  rm -f /tmp/_img_check
fi
