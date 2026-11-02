# Shared by install.sh and update.sh: installing from a content pack. Source it; needs
# log() and $PACK.

pack_debs() {  # install (or upgrade to) the pack's debs from it as a local apt repository
    # Updates come from content packs, not the internet: Ubuntu's daily apt runs only hang
    # offline, holding apt's locks (a fresh install's first-boot `apt-get update` did, here)
    systemctl disable --now apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true
    local apt_dir
    apt_dir=$(mktemp -d)
    mkdir -p "$apt_dir/lists/partial"
    echo "deb [trusted=yes] file:$PACK/debs ./" > "$apt_dir/sources.list"
    # Only the pack's repository, with its own lists, so a stuck `apt-get update` elsewhere
    # (it holds /var/lib/apt/lists/lock) doesn't block this one
    apt_() {
        DEBIAN_FRONTEND=noninteractive apt-get -q -o DPkg::Lock::Timeout=600 \
            -o Dir::Etc::SourceList="$apt_dir/sources.list" -o Dir::Etc::SourceParts=/nonexistent \
            -o Dir::State::Lists="$apt_dir/lists" "$@"
    }
    apt_ update >/dev/null
    # --force-confold: keep config files the box has changed (Docker's daemon.json)
    # shellcheck disable=SC2046
    apt_ install -y --no-install-recommends -o Dpkg::Options::=--force-confold \
        $(cat "$PACK/debs/WANT") >/dev/null
    rm -rf "$apt_dir"
}

pack_images() {  # docker load every image of the pack this machine doesn't have yet
    local img file id loaded=0
    while IFS=$'\t' read -r img file; do
        id=$(cat "$PACK/images/.$file.id" 2>/dev/null || true)
        if [[ -n "$id" && "$(docker image inspect -f '{{.Id}}' "$img" 2>/dev/null)" == "$id" ]]; then
            continue
        fi
        log "loading $img"
        zstd -dc "$PACK/images/$file" | docker load -q >/dev/null
        loaded=$((loaded + 1))
    done < "$PACK/images/IMAGES"
    log "$loaded image(s) loaded, $(( $(wc -l < "$PACK/images/IMAGES") - loaded )) already here"
}

pack_os_check() {  # the pack's debs are for one Ubuntu release (24.04.x matches 24.04)
    . /etc/os-release
    local pack_os
    pack_os=$(cat "$PACK/debs/OS")
    [[ "$pack_os" == *"Ubuntu $VERSION_ID"* ]] || die "the pack's packages are for $pack_os; this is $PRETTY_NAME"
}
