# Presigned URL 업로드 시 400 에러 분석 및 FE 대응

## 현상

- Presigned URL 요청 후 전달받은 `uploadUrl`로 파일을 PUT 전송할 때 **특정 파일**에서만 **HTTP 400** 발생
- Presigned 요청 시의 `contentType`과 PUT 시 `Content-Type` 헤더를 동일하게 맞춰서 보내고 있음

---

## 원인 분석 (백엔드 기준)

### 1. 400은 **저장소(S3/MinIO)** 에서 반환됨

- `uploadUrl`은 **우리 API 서버가 아니라 S3/MinIO 주소**입니다.
- 따라서 **400 응답은 우리 백엔드가 아니라 스토리지(S3/MinIO)** 에서 내려옵니다.
- Presigned PUT에서 스토리지가 400(또는 403)을 주는 대표 이유는 **서명 시 사용한 조건과 실제 요청이 다를 때**입니다.

### 2. Presigned URL 서명 조건

백엔드는 Presigned URL을 아래처럼 생성합니다.

```python
# main.py: generate_presigned_url("put_object", Params={..., "ContentType": contentType})
url = s3_client.generate_presigned_url(
    "put_object",
    Params={"Bucket": S3_BUCKET, "Key": object_key, "ContentType": contentType},
    ExpiresIn=PRESIGNED_URL_EXPIRES_SEC,
)
```

- 여기서 쓰는 `contentType`은 **presigned-url API 호출 시 쿼리 파라미터로 받은 값 그대로**입니다.
- 이 값이 **PUT 요청의 `Content-Type` 헤더와 1바이트 단위로 같아야** 서명 검증이 통과합니다.
- 조금이라도 다르면(공백, 쿼리 인코딩 차이, 대소문자, `charset` 추가 등) 스토리지가 **서명 불일치**로 400/403을 반환할 수 있습니다.

### 3. “특정 파일”에서만 나는 이유로 추정되는 것

| 가능 원인 | 설명 |
|-----------|------|
| **`file.type`이 빈 문자열** | 일부 환경(드래그 앤 드롭, 특정 확장자/OS 조합)에서 `File.type`이 `""`입니다. Presigned는 `contentType=image/jpeg` 등으로 요청했는데, PUT에서는 `Content-Type: file.type`(빈 값)으로 보내면 **서명 시 사용한 값과 달라져** 400/403 발생. |
| **Presigned와 PUT에 서로 다른 값 사용** | Presigned 요청에는 A(예: `image/jpeg`)를 쓰고, PUT 시에는 B(예: `file.type` 또는 다른 기본값)를 쓰면 서명 불일치. |
| **헤더 값의 미세한 차이** | `image/jpeg` vs `image/jpeg `(끝 공백), `image/jpeg` vs `image/jpeg; charset=utf-8` 등은 서로 다른 값으로 취급됨. |
| **쿼리 파라미터 인코딩** | Presigned 요청 시 `contentType`을 URL 인코딩했다가 디코딩했을 때 공백/특수문자 등이 달라지면, 서명에 반영된 값과 PUT 시 헤더가 어긋날 수 있음. |

---

## FE 측 권장 대응

### 1. **한 번 정한 값을 Presigned와 PUT 양쪽에 동일하게 사용**

- Presigned URL 요청에 넣는 `contentType`과, `uploadUrl`로 PUT 할 때 넣는 `Content-Type` 헤더 값을 **같은 변수 하나**로 통일하는 것이 가장 중요합니다.

```ts
// 권장: 하나의 contentType을 정해서 Presigned 요청과 PUT 헤더에 동일하게 사용
const contentType = file.type && file.type.trim() !== "" ? file.type : "image/jpeg";
const { uploadUrl, receiptId, objectKey } = await getPresignedUrl(fileName, contentType, userUuid, type);

await fetch(uploadUrl, {
  method: "PUT",
  body: file,
  headers: { "Content-Type": contentType },  // Presigned 요청과 동일한 값
});
```

- `file.type`이 비어 있거나 불안정한 경우를 대비해, **Presigned 호출 시와 PUT 시 모두** 위에서 정한 `contentType`(예: 기본값 `image/jpeg`)을 사용해야 합니다.

### 2. **PUT 요청 시 추가 헤더 금지**

- `Content-Type` 외에 **서명에 포함되지 않은 헤더**를 붙이면 서명 검증이 실패할 수 있습니다.
- 필요한 최소 헤더만 두는 것이 안전합니다. (실제로 서명에 쓰이는 것은 보통 `Content-Type` 등 소수입니다.)

### 3. **디버깅 시 확인할 것**

- Presigned URL 요청 시 쿼리 파라미터 `contentType`의 **실제 전송 값** (개발자 도구 Network 탭)
- PUT 요청의 **Request Headers** 안 `Content-Type` 값
- 위 두 값이 **완전히 동일한지** (앞뒤 공백, `; charset=...` 등 없이) 확인

---

## 백엔드 측 보완 (선택)

- Presigned URL 발급 시 `contentType`이 비어 있거나 유효하지 않으면 **기본값 `image/jpeg`** 로 넣어서 서명하도록 할 수 있습니다.
- 이렇게 하면 FE가 Presigned를 빈 값으로 요청해도, PUT에서 `Content-Type: image/jpeg`를 보내면 일치하게 됩니다.
- 다만 **근본 해결은 FE에서 Presigned 요청과 PUT 요청에 동일한 Content-Type 값을 사용하는 것**입니다.

---

## 요약

| 항목 | 내용 |
|------|------|
| **400 발생 위치** | 우리 API가 아니라 **S3/MinIO(uploadUrl)** |
| **주요 원인** | Presigned 생성 시 사용한 `ContentType`과 PUT 요청의 `Content-Type` **불일치** (특히 `file.type` 빈 문자열 시) |
| **FE 조치** | Presigned 요청과 PUT 요청에 **동일한 contentType 한 값** 사용 (빈 값이면 `image/jpeg` 등으로 통일), 추가 헤더 최소화 |
| **검증** | Network 탭에서 Presigned 쿼리 `contentType`과 PUT 헤더 `Content-Type` 문자열이 완전히 같은지 확인 |
