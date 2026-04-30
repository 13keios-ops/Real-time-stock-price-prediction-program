# 버전 관리

## 현재 규칙

이 저장소는 root `VERSION` 파일을 release 준비 완료 신호로 사용한다.

- 현재 버전: `0.2.0`
- 브랜치: `main`
- watcher 설정: `autopush.json`
- 트리거: `version-change`
- 현재 opt-in: `enabled=true`
- git-autopush helper 기본 `ScanRoot`: `D:\GitHub`

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

## 권장 흐름

1. 코드와 문서를 정리한다.
2. 테스트를 돌린다.
3. `VERSION` 을 마지막에 바꾼다.
4. 필요하면 명시적으로 commit 한다.
5. watcher가 새 버전을 감지하고 push 상태를 갱신한다.

## 명령

버전 갱신:

```powershell
.\scripts\bump_version.ps1 -Version 0.2.1
```

수동 commit 예시:

```powershell
git add -A
git commit -m "chore(release): v0.2.1"
```

## 메모

- 이 저장소는 watcher opt-in 상태다.
- watcher는 `VERSION` 변화를 기준으로만 동작한다.
- `HEAD`가 이미 해당 버전을 포함하면 watcher는 새 auto-commit을 만들지 않고 기존 commit을 push할 수 있다.
- 관련 watcher / audit 스크립트는 `git` 이 PATH 에 없거나 PATH 의 git 경로가 실제 파일로 존재하지 않으면 GitHub Desktop 내장 `git.exe` 를 찾아 사용한다.
