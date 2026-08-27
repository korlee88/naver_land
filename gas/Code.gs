// Google Apps Script — 구글시트 백업/복원 엔드포인트
//
// 배포 위치: db.py의 GAS_URL이 가리키는 스프레드시트("부동산")
//   (확장 프로그램 → Apps Script 에디터에 이 파일 내용을 붙여넣고 재배포)
//
// spreadsheet_id 파라미터를 주면 이 스크립트가 바인딩된 시트가 아니라
// 해당 ID의 다른 스프레드시트를 연다(같은 계정 소유/편집 권한이 있어야 함).
// KOSIS 통계는 구글시트 셀 개수 한도(통합문서당 1천만 셀)를 "부동산" 시트가
// 이미 거의 다 채워서 별도 시트(KOSIS_SHEET_ID, db.py)로 분리해 저장한다.
//
// 재배포 방법:
//   1. Apps Script 에디터에서 기존 코드를 이 내용으로 교체 후 저장(Ctrl+S)
//   2. 배포 → 배포 관리 → 기존 배포 옆 연필(수정) 아이콘 클릭
//   3. 버전: "새 버전" 선택 → 배포
//      (반드시 "수정"으로 같은 URL을 유지해야 db.py의 GAS_URL이 계속 작동함)

const SHEET_NAME = "기록";
const TOKEN = "MY_SECRET_TOKEN";

function _openSpreadsheet(spreadsheetId) {
  return spreadsheetId
    ? SpreadsheetApp.openById(spreadsheetId)
    : SpreadsheetApp.getActiveSpreadsheet();
}

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);

    if (!body || body.token !== TOKEN) {
      return ContentService.createTextOutput("Unauthorized");
    }

    const rows = body.rows || [];
    if (!rows.length) {
      return ContentService.createTextOutput("No rows");
    }

    // ✅ sheet_name이 지정되면 해당 시트(없으면 자동 생성)에 쓴다.
    //    미지정 시 기존 "기록" 시트 사용 (하위 호환).
    const targetSheetName = body.sheet_name || SHEET_NAME;
    const ss = _openSpreadsheet(body.spreadsheet_id);
    let sheet = ss.getSheetByName(targetSheetName);

    if (!sheet) {
      sheet = ss.insertSheet(targetSheetName);
    }

    if (body.sheet_name) {
      // RTMS매매/RTMS전월세/KOSIS통계 등 — 매번 DB 전체 스냅샷을 보내므로 덮어쓰기
      sheet.clearContents();
      sheet.getRange(1, 1, rows.length, rows[0].length).setValues(rows);
    } else {
      // 기존 "기록" 시트 — 누적 append 유지
      sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
    }

    return ContentService.createTextOutput("OK");
  } catch (err) {
    return ContentService.createTextOutput("ERR: " + err);
  }
}

function doGet(e) {
  try {
    if (e.parameter.token !== TOKEN) {
      return ContentService
        .createTextOutput(JSON.stringify({error: "Unauthorized"}))
        .setMimeType(ContentService.MimeType.JSON);
    }
    const sheetName = e.parameter.sheet_name || "APT_RAWDATA";
    const ss = _openSpreadsheet(e.parameter.spreadsheet_id);
    const sh = ss.getSheetByName(sheetName);
    if (!sh) {
      return ContentService
        .createTextOutput(JSON.stringify({error: "Sheet not found"}))
        .setMimeType(ContentService.MimeType.JSON);
    }
    const data = sh.getDataRange().getValues();
    return ContentService
      .createTextOutput(JSON.stringify({rows: data}))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({error: "ERR: " + err}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
