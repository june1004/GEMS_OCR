# Complete 요청 시 403 "receiptId owner mismatch" 분석 및 FE 대응

## 현상

- **파일 업로드 후 complete 요청 시 403 Forbidden**
- 메시지: `"receiptId owner mismatch (userUuid must match the one used for presigned-url)"`
- **특정 사용자**에서만 발생
- 해당 사용자의 userUuid는 `+`, `/`, `=` 등이 포함된 **Base64 형태** 문자열 (예: `+Qe2Wo1Fg++OlWSl1nTLWkCmdqDqOgJzlszGjWh83KzhQf29GOd+wASMqMLKVtgRsEddKKgLHWv4oNuRxY7L1g==`)

---

## 원인 분석

### 1. 서버에서의 비교 방식

- **Presigned URL 요청** 시: `userUuid`를 **쿼리 파라미터**로 받아 정규화 후 DB에 저장
- **Complete 요청** 시: `userUuid`를 **JSON body**로 받아 정규화 후, 저장된 값과 **1:1 비교**
- 두 값이 다르면 403 발생

### 2. 왜 “특정 사용자”에서만 발생하는가

이번에 문제가 된 userUuid들은 **`+`가 포함된 Base64 문자열**입니다.

| 구분 | Presigned URL (1단계) | Complete (3단계) |
|------|------------------------|------------------|
| **전달 방식** | 쿼리 스트링 (`?userUuid=...`) | JSON body (`{"userUuid": "..."}`) |
| **`+` 처리** | 쿼리 스트링 규칙상 **`+`가 공백(space)으로 해석**될 수 있음 | JSON에서는 **`+`가 그대로** 전달됨 |

따라서:

1. **Presigned** 호출 시  
   - FE가 `userUuid=+Qe2Wo1Fg++OlWSl1nTLWk...` 처럼 **인코딩 없이** 쿼리에 넣으면  
   - 서버는 `+`를 공백으로 받아  
     `" Qe2Wo1Fg  OlWSl1nTLWk..."` (공백 2개) 로 인식할 수 있음  
   - 백엔드는 공백을 `+`로 되돌려 저장하므로, **연속 공백이 하나로 합쳐지지 않았다면**  
     `"+Qe2Wo1Fg++OlWSl1nTLWk..."` 로 저장됨  

2. **중요한 예외**  
   - 브라우저/프록시/서버 중 한 곳에서 **연속 공백을 하나로 합치는** 동작이 있으면  
     `"  "` → `" "` 가 되어  
   - 저장 시 `"++"` 가 `"+"` 한 개로 바뀌어 저장될 수 있음  

3. **Complete** 호출 시  
   - FE는 원본 그대로 `"+Qe2Wo1Fg++OlWSl1nTLWk..."` 를 JSON으로 전송  
   - 서버는 이를 그대로 정규화  
   - 이때 **저장값은 이미 `+`가 하나 줄어든 상태**이므로  
     **저장값 ≠ Complete로 보낸 값** → **403 owner mismatch** 발생  

즉, **userUuid에 `+`가 들어가는 사용자**일수록, 쿼리 스트링 해석과 “공백 합침” 여부에 따라 불일치가 나기 쉽습니다.

### 3. 정리

- **Presigned**의 `userUuid`는 **쿼리 스트링**이라 `+`가 공백으로 바뀌거나, 연속 공백이 합쳐질 수 있음.
- **Complete**의 `userUuid`는 **JSON**이라 `+`가 그대로 전달됨.
- 그 결과, **같은 사용자임에도** 서버에 저장된 값과 Complete로 보낸 값이 달라져 403이 발생함.

---

## FE 권장 수정 사항

### 1. Presigned URL 호출 시 userUuid 반드시 인코딩

쿼리 스트링에 넣을 때 **`+`를 비롯해 `/`, `=` 등이 그대로 나가지 않도록** 인코딩해야 합니다.

**권장: `URLSearchParams` 사용 (자동 인코딩)**

```ts
const params = new URLSearchParams();
params.set("fileName", fileName);
params.set("contentType", contentType);
params.set("userUuid", userUuid);  // 내부적으로 encodeURIComponent 처리
params.set("type", type);
const res = await fetch(`${API_BASE}/api/v1/receipts/presigned-url?${params.toString()}`, {
  method: "POST",
});
```

또는 **직접 인코딩**:

```ts
const query = [
  `fileName=${encodeURIComponent(fileName)}`,
  `contentType=${encodeURIComponent(contentType)}`,
  `userUuid=${encodeURIComponent(userUuid)}`,  // + → %2B, / → %2F 등
  `type=${encodeURIComponent(type)}`,
].join("&");
const res = await fetch(`${API_BASE}/api/v1/receipts/presigned-url?${query}`, { method: "POST" });
```

- `encodeURIComponent(userUuid)` 를 쓰면 `+`는 `%2B`로 넘어가서, 서버가 **공백으로 해석하지 않음**.
- Presigned 시점에 저장되는 값과 Complete 시점에 보내는 값이 **동일한 문자열**로 맞춰져 403을 피할 수 있습니다.

### 2. Presigned와 Complete에 “같은” userUuid 사용

- Presigned 호출에 사용한 **그대로의 userUuid 문자열**을 저장해 두고,
- Complete 요청 시 **그 저장한 값을 그대로** JSON의 `userUuid`에 넣어야 합니다.
- Presigned는 **반드시 인코딩된 쿼리**로, Complete는 **동일한 문자열을 JSON**으로 보내면 됩니다.

### 3. 이미 403이 난 receiptId에 대해

- 해당 receiptId는 **Presigned 시 잘못된(짧아진) userUuid로 이미 저장**된 상태일 수 있습니다.
- 같은 receiptId로 Complete를 다시 보내도, **저장된 값이 원래 userUuid와 다르면** 403이 계속 납니다.
- **해당 건은 새로 Presigned → 업로드 → Complete** 하도록 안내하는 것이 좋습니다 (새 receiptId로 진행).

---

## 백엔드 동작 요약

- Presigned/Complete 모두 **동일한 정규화 함수**를 사용합니다.
  - URL 디코딩 반복 (예: `%253D` → `=`)
  - 쿼리에서 공백으로 바뀐 부분을 `+`로 복원
- 다만 **이미 “연속 공백 → 하나로 합쳐진” 상태로 저장된 값**은 서버만으로는 원래의 `++`를 복구할 수 없습니다.
- 따라서 **근본 해결은 FE에서 Presigned 요청 시 userUuid를 반드시 인코딩하는 것**입니다.

---

## 참고: 동일 FE 코드베이스인 경우

- 이 프로젝트의 `frontend/src/api/receipts.ts` 는 이미 `URLSearchParams`로 presigned URL을 호출하고 있어, **같은 코드를 쓰는 클라이언트**라면 `+`는 `%2B`로 전달되는 것이 정상입니다.
- 403이 나는 클라이언트가 **다른 앱/웹(다른 코드베이스)** 이라면, 그쪽에서 presigned 호출 시 **userUuid를 쿼리에 인코딩하지 않고** 넣고 있을 가능성이 큽니다.
- 같은 코드베이스인데도 403이 난다면, **Presigned 호출 시 사용한 userUuid와 Complete 호출 시 사용한 userUuid가 서로 다른 출처**일 수 있습니다.  
  (예: presigned 직후 받은 값이 아닌, URL/저장소에서 다시 읽은 값으로 complete를 보내면서, 그 과정에서 공백/인코딩이 바뀐 경우)  
  → **Presigned 호출에 넣었던 userUuid 문자열을 그대로 저장해 두고, Complete 시에는 반드시 그 값을 그대로** 사용하세요.

---

## FE에 전달할 요약 문구 (복사용)

> Complete 403 "receiptId owner mismatch"는 **Presigned URL 요청 시 userUuid가 쿼리 스트링에서 `+`가 공백으로 바뀌거나, 연속 공백이 합쳐지면서** 서버에 저장된 값과 Complete 시 보내는 userUuid가 달라져서 발생합니다.  
>  
> **해결 방법:**  
> 1. Presigned URL 호출 시 **쿼리 파라미터에 userUuid를 반드시 인코딩**해 주세요.  
>    - `URLSearchParams`를 사용하거나,  
>    - `encodeURIComponent(userUuid)` 로 넣어서 `+`가 `%2B`로 전달되도록 하면 됩니다.  
> 2. **Presigned에 보낸 userUuid와 Complete에 보낼 userUuid를 완전히 동일한 문자열**로 두세요.  
>    - Presigned 직후 받은 receiptId와 **같이 저장한 userUuid**를 Complete 시 그대로 사용하는 것이 안전합니다.  
>  
> 이미 403이 난 receiptId는 예전에 잘못 저장된 값이라 그대로는 해결되지 않을 수 있으니, **해당 건은 새 receiptId로 Presigned → 업로드 → Complete** 하면 됩니다.
