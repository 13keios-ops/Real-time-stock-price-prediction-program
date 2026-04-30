# Git 자동 Push 관리자

## 1. 목표

이 문서는 하나의 루트 폴더 아래에 있는 여러 로컬 Git 저장소를 감시하고, 저장소 버전이 바뀌었을 때만 안전하게 `git commit` 과 `git push` 를 실행하는 방법을 정의한다.

권장 대상 구조는 아래와 같다.

```text
D:\GitHub\
  Project-A\
    .git\
    VERSION
    autopush.json
  Project-B\
    .git\
    VERSION
    autopush.json
  Project-C\
    .git\
```

watcher 스크립트 하나가 루트 폴더를 확인하고, `autopush.json` 이 있는 저장소만 명시적 opt-in 대상으로 처리한다.

## 2. 중요한 경계

GitHub 자체는 로컬 폴더를 직접 감시할 수 없다.

실제 흐름은 아래와 같다.

1. 사용자 PC에서 PowerShell 스크립트가 실행된다.
2. 스크립트가 로컬 저장소를 스캔한다.
3. opt-in 된 저장소에서 유효한 버전 변경을 감지하면 `git commit` 과 `git push` 를 실행한다.
4. GitHub는 push 된 commit을 일반 원격 변경으로 받는다.

## 3. 권장 안전 모델

모든 파일 변경을 모든 저장소에서 자동 push 하지 않는다.

권장 규칙은 아래와 같다.

- 모든 저장소를 보는 watcher 스크립트는 하나만 둔다.
- 저장소마다 `autopush.json` 을 하나씩 둔다.
- 기본 opt-in 은 꺼둔다.
- trigger는 `VERSION` 파일 변경으로 제한한다.
- 설정된 branch 에서만 실행한다.

이 방식은 관련 없는 프로젝트의 미완성 작업이 함께 push 되는 사고를 줄인다.

## 4. 이 저장소에 추가된 파일

- `scripts/watch_git_versions_and_push.ps1`
- `config/autopush.project.schema.json`
- `config/autopush.project.example.json`
- `scripts/bootstrap_git_autopush_targets.ps1`
- `scripts/install_git_autopush_startup_launcher.ps1`
- `scripts/remove_git_autopush_startup_launcher.ps1`
- `scripts/audit_git_autopush_targets.ps1`
- `scripts/set_git_autopush_enabled.ps1`

watcher 상태와 로그는 `runtime-data/autopush/` 아래에 남긴다.

하나의 루트 아래 여러 저장소에 시작용 `VERSION` 과 `autopush.json` 을 배치하려면 아래를 사용한다.

```powershell
.\scripts\bootstrap_git_autopush_targets.ps1 -ScanRoot 'D:\GitHub'
```

bootstrap 기본값은 아래와 같다.

- 저장소가 `main` branch 이고, `origin` 이 있으며, 작업 트리가 깨끗할 때만 `enabled=true` 로 둔다.
- dirty 상태이거나 `main` 이 아닌 저장소는 `enabled=false` 설정 파일만 준비한다.
- `VERSION` 파일이 없으면 `0.1.0` 으로 초기화한다.

현재 어떤 저장소를 켤 수 있는지 점검하려면 아래를 사용한다.

```powershell
.\scripts\audit_git_autopush_targets.ps1 -ScanRoot 'D:\GitHub'
```

한 저장소가 안전한 상태가 된 뒤 opt-in 을 켜려면 아래를 사용한다.

```powershell
.\scripts\set_git_autopush_enabled.ps1 -RepoPath 'D:\GitHub\Instargram Card News' -Enable
```

이 enable 스크립트는 명시적 override 없이 dirty 저장소나 `main` 이 아닌 저장소를 켜지 않는다.

## 4.1 실제 버전 감지 방식

opt-in 된 저장소에서 watcher는 임의 파일 변경으로 release 시점을 추측하지 않는다.

확인 순서는 아래와 같다.

- `autopush.json` 존재 여부
- `enabled=true` 여부
- 현재 branch 가 설정 branch 와 일치하는지
- `VERSION` 존재 여부
- 현재 `VERSION` 값이 `runtime-data/autopush/git-autopush-state.json` 에 기록된 마지막 push 버전과 다른지

이 조건을 모두 만족할 때만 stage, commit, push 로직으로 넘어간다.

## 5. 저장소별 설정

자동 관리가 필요한 저장소는 저장소 root에 `autopush.json` 파일이 필요하다.

예시는 아래와 같다.

```json
{
  "enabled": true,
  "branch": "main",
  "remote": "origin",
  "trigger": "version-change",
  "version_file": "VERSION",
  "stage_mode": "all",
  "commit_message": "chore(release): v{version}",
  "commit_body_mode": "staged-summary",
  "commit_body_header": "Auto-generated change summary",
  "push_tag": false,
  "tag_name": "v{version}"
}
```

필드 의미는 아래와 같다.

- `enabled`: 저장소 opt-in 스위치
- `branch`: 현재 branch 가 이 값과 같을 때만 push
- `remote`: 보통 `origin`
- `trigger`: 현재는 `version-change` 만 사용
- `version_file`: 보통 `VERSION`
- `stage_mode`
- `all`: 전체 변경을 `git add -A` 로 올린다.
- `tracked`: 추적 중인 변경만 `git add -u` 로 올린다.
  - `version-only`: 버전 파일만 stage
- `commit_message`: `{version}`, `{repo}`, `{branch}` 사용 가능
- `commit_body_mode`
  - `staged-summary`: staged 파일 변경과 diffstat으로 commit 설명 자동 생성
  - `none`: 첫 줄 요약만 commit
- `commit_body_header`: `{version}`, `{repo}`, `{branch}` 사용 가능
- `push_tag`: `true` 이면 tag 도 생성하고 push
- `tag_name`: `{version}`, `{repo}`, `{branch}` 사용 가능

## 6. 권장 작업 흐름

가장 안전한 루틴은 아래와 같다.

1. 대상 저장소에서 코드와 문서를 모두 정리한다.
2. 테스트를 돌린다.
3. 마지막에 `VERSION` 파일을 바꾼다.
4. watcher가 버전 변경을 감지한다.
5. watcher가 자동 commit과 push를 수행한다.

`stage_mode=all` 에서 버전 변경은 “release 준비 완료” 신호다.
`commit_body_mode=staged-summary` 를 쓰면 commit 제목은 버전 중심으로 유지하고, 본문에는 staged diff 요약이 자동으로 채워진다.

## 7. watcher 동작

opt-in 된 저장소마다 watcher는 아래를 수행한다.

1. `.git` 과 `autopush.json` 확인
2. 현재 branch 검증
3. 설정된 버전 파일 읽기
4. 마지막 성공 push 버전과 현재 버전 비교
5. 버전이 바뀌었으면 아래 수행
   - 변경 파일 stage
   - 설정된 메시지로 commit
   - 설정된 원격 branch 로 push
   - 옵션에 따라 tag 생성과 push

버전이 바뀌지 않았으면 저장소를 건너뛴다.

현재 스크립트의 안전 보강은 아래와 같다.

- 설정 branch 가 원격 branch 보다 뒤처져 있으면 stale history 위에 자동 commit 을 만들지 않도록 건너뛴다.
- `HEAD` 가 이미 대상 `VERSION` 을 포함하면 unrelated dirty 파일을 새 commit 에 쓸어 담지 않고 기존 commit 을 push 한다.
- Git 이 merge, rebase, cherry-pick 류 작업 중이면 저장소를 건너뛴다.
- `git.exe` 는 PATH 에서 먼저 찾고, 없으면 GitHub Desktop 번들 Git을 사용한다.
- 자동 commit 설명은 staged 변경 상태와 `git diff --cached --stat` 으로 만든다.

## 8. 1회 실행과 상시 실행

1회 스캔:

```powershell
.\scripts\watch_git_versions_and_push.ps1 -ScanRoot 'D:\GitHub' -Once
```

상시 실행:

```powershell
.\scripts\watch_git_versions_and_push.ps1 -ScanRoot 'D:\GitHub' -PollSeconds 60
```

재귀 스캔:

```powershell
.\scripts\watch_git_versions_and_push.ps1 -ScanRoot 'D:\GitHub' -PollSeconds 60 -Recurse
```

## 9. Windows 로그인 시 시작

로그인 시 watcher를 자동으로 시작하려면 아래를 사용한다.

```powershell
.\scripts\register_git_autopush_task.ps1 -ScanRoot 'D:\GitHub' -PollSeconds 60
```

재귀 스캔 예시는 아래와 같다.

```powershell
.\scripts\register_git_autopush_task.ps1 -ScanRoot 'D:\GitHub' -PollSeconds 60 -Recurse
```

이 명령은 `GitAutoPushWatcher` 라는 Windows 예약 작업을 만든다.

수동 제어 스크립트:

```powershell
.\scripts\get_git_autopush_watcher_status.ps1
.\scripts\start_git_autopush_watcher.ps1 -EnsureRegistered
.\scripts\stop_git_autopush_watcher.ps1
```

이 스크립트들은 직접 운영할 때와 Codex 자동화가 상태 확인 또는 재시작을 해야 할 때 유용하다.

`Register-ScheduledTask` 가 `Access is denied` 를 반환하면 시작프로그램 폴더 launcher를 대신 사용한다.

```powershell
.\scripts\install_git_autopush_startup_launcher.ps1 -ScanRoot 'D:\GitHub' -PollSeconds 60
```

제거:

```powershell
.\scripts\remove_git_autopush_startup_launcher.ps1
```

이 방법은 작업 스케줄러 권한 문제를 피하면서 현재 사용자 로그인 시 watcher를 시작한다.

## 10. 상태와 로그

기본 파일은 아래와 같다.

- `runtime-data/autopush/git-autopush.log`
- `runtime-data/autopush/git-autopush-state.json`

상태 파일은 같은 버전이 반복 push 되는 것을 막는다.

## 10.1 Smoke 테스트

저장소에는 통합형 테스트 스크립트도 있다.

```powershell
.\scripts\test_git_autopush_watcher.ps1
```

테스트는 `.tmp-tests/` 아래 임시 저장소를 만들고 아래를 검증한다.

- watcher 하나가 하나의 루트에서 여러 저장소를 스캔
- `autopush.json` opt-in 동작
- `VERSION` 변경 시 자동 commit/push
- staged 변경에서 자동 commit 설명 생성
- 이미 commit 된 release 를 push 할 때 unrelated untracked 파일을 자동 commit 하지 않는 안전 동작

## 11. 권장 사용 정책

권장:

- 의도적으로 opt-in 한 저장소에만 사용한다.
- 저장소가 정말 준비됐을 때만 `VERSION` 을 바꾼다.
- `branch` 는 `main` 또는 별도 release branch 로 고정한다.

권장하지 않음:

- `D:\GitHub` 아래 모든 저장소를 무조건 활성화
- `VERSION` 을 작업 초반에 자주 바꾸는 습관에서 `stage_mode=all` 사용
- 비밀정보, 생성 파일, 불안정한 작업 트리가 있는 저장소 자동 push

## 12. 권장 기본값

대부분의 프로젝트는 아래 설정으로 시작하는 것이 가장 안전하다.

```json
{
  "enabled": true,
  "branch": "main",
  "remote": "origin",
  "trigger": "version-change",
  "version_file": "VERSION",
  "stage_mode": "all",
  "commit_message": "chore(release): v{version}",
  "commit_body_mode": "staged-summary",
  "commit_body_header": "Auto-generated change summary",
  "push_tag": false,
  "tag_name": "v{version}"
}
```

이 설정은 아래 장점을 준다.

- 모든 프로젝트를 보는 watcher 하나
- 저장소별 명시적 opt-in
- 버전 기반 release 신호
- 수동 반복 없이 자동 commit 과 push
