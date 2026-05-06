# 버전 관리

## 현재 규칙

이 저장소는 root `VERSION` 파일을 release 준비 완료 신호로 사용한다.

- 현재 버전: `0.2.0`
- 브랜치: `main`
- watcher 설정: `autopush.json`
- 트리거: `version-change`
- 현재 opt-in: `enabled=true`
- git-autopush helper 기본 `ScanRoot`: 현재 저장소 root

## 버전 변경 감지 방식

버전 변경 감지는 아래 흐름으로 이뤄진다.

1. watcher가 저장소 root의 `autopush.json`을 읽는다.
2. `enabled=true` 인 저장소만 감시한다.
3. `version_file` 설정값으로 root `VERSION` 파일을 읽는다.
4. `runtime-data/autopush/git-autopush-state.json` 에 기록된 마지막 push 버전과 현재 `VERSION` 값을 비교한다.
5. 값이 달라지면 watcher가 stage, commit, push 또는 기존 release commit push를 수행한다.

확인 위치는 아래와 같다.

- 감시기 로그: `runtime-data/autopush/git-autopush.log`
- 감시기 상태: `runtime-data/autopush/git-autopush-state.json`

WSL2 이전 후 현재 감시 기준은 아래처럼 저장소 root 자체로 둔다.

```bash
./scripts/start_git_autopush_watcher.sh --scan-root "$PWD"
```

WSL `git push`가 GitHub HTTPS 자격 증명 프롬프트에서 멈추는 경우, watcher는 Windows GitHub Desktop에 저장된 Git 자격 증명을 사용해 같은 WSL 작업 폴더를 push하는 fallback을 시도한다. 비밀값은 저장소 파일에 쓰지 않는다.

## 권장 흐름

1. 코드와 문서를 정리한다.
2. 테스트를 돌린다.
3. `VERSION` 을 마지막에 바꾼다.
4. 필요하면 명시적으로 commit 한다.
5. watcher가 새 버전을 감지하고 push 상태를 갱신한다.

## 명령

버전 갱신:

```bash
./scripts/bump_version.sh -Version 0.2.1
```

수동 commit 예시:

```bash
git add -A
git commit -m "chore(release): v0.2.1"
```

## 메모

- 이 저장소는 watcher opt-in 상태다.
- watcher는 `VERSION` 변화를 기준으로만 동작한다.
- `HEAD`가 이미 해당 버전을 포함하면 watcher는 새 auto-commit을 만들지 않고 기존 commit을 push할 수 있다.
- 관련 watcher / audit 스크립트는 WSL2의 `git` 을 우선 사용하고, GitHub HTTPS 인증 실패 시 Windows GitHub Desktop `git.exe` push fallback을 사용한다.
