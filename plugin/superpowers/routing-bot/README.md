# superpowers 라우팅 봇

`delegation_request` 스키마를 구독하는 `AgoraBot` 서브클래스다. superpowers 페르소나 워커가
다른 역할에 작업을 위임할 때 이 스키마로 메시지를 emit하면, 봇이 `agora.find`로 대상 워커를
resolve해 `agora.bot_emit(target=...)` 으로 직접 전달한다.

## 기동

서버 기동 후, 페르소나 워커보다 먼저 실행한다:

- Windows: `run-bot.bat`
- Unix: `run-bot.sh`

## 런타임 파일

이 디렉터리의 두 파일을 배포 루트의 `.agentagora/`에 설치해야 서버가 올바르게 로드한다:

- `comm-matrix.csv` → `<dir>/.agentagora/comm-matrix.csv`
- `delegation_request.schema.jsonl` → `<dir>/.agentagora/schemas.jsonl` 에 append

## ACL 참고

`agora.bot_emit(target=...)` 경로는 comm-matrix ACL을 독립적으로 재검사하지 않는다.
ACL은 `agora.dispatch` / `agora.broadcast` 호출 시에만 검사된다. 라우팅 봇은
§9 워크플로의 고정된 엣지를 따라 라우팅하는 신뢰된 인프라이므로 이는 허용된 설계다.
향후 강화 후보: 봇 내부에서 comm-matrix를 로드해 라우팅 전 ACL을 추가 검증.
