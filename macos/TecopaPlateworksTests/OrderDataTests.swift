import XCTest

final class OrderDataTests: XCTestCase {
    func testPreviewSizesParseInOrderWithTheirReasons() {
        let json = #"""
        {"sizes": [
          {"key": "11x17", "offered": true, "orientation": "portrait", "print_in": [11, 17], "panels": 1, "gap": 0, "warning": ""},
          {"key": "two", "offered": false, "orientation": "landscape", "print_in": [46, 17], "panels": 2, "gap": 2,
           "why": "the tracks span 24% of the sheet's width, under 30%"}
        ]}
        """#
        let sizes = PreviewSize.parse(Data(json.utf8))
        XCTAssertEqual(sizes.map(\.key), ["11x17", "two"])
        XCTAssertEqual(sizes[0].label, "11 × 17 (11 × 17 in)")
        XCTAssertNil(sizes[0].warning)
        XCTAssertFalse(sizes[1].offered)
        XCTAssertEqual(sizes[1].why, "the tracks span 24% of the sheet's width, under 30%")
        XCTAssertEqual(sizes[1].label, "Set of two (46 × 17 in)")
        XCTAssertEqual(PreviewSize.parse(Data("not json".utf8)), [])
    }

    func testTheDeskRowIsFoundByOrderNumber() {
        let json = #"""
        {"records": {"tecopa": [
          {"order_id": "TP-26-001", "size": "17x22", "paid": "2026-11-02", "status": "paid"},
          {"order_id": "TP-26-002", "size": "", "paid": "", "status": "preview_sent"}
        ], "lab": []}}
        """#
        let d = Data(json.utf8)
        XCTAssertEqual(DeskOrder.find("TP-26-001", in: d),
                       DeskOrder(orderID: "TP-26-001", size: "17x22", paid: true, status: "paid"))
        XCTAssertEqual(DeskOrder.find("TP-26-002", in: d)?.paid, false)
        XCTAssertNil(DeskOrder.find("TP-26-999", in: d))
    }

    func testDeskSizeTextMatchesTheSizeKey() {
        XCTAssertTrue(deskSizeMatches("17x22", key: "17x22"))
        XCTAssertTrue(deskSizeMatches("17 × 22 in", key: "17x22"))
        XCTAssertTrue(deskSizeMatches("22x17", key: "17x22"))
        XCTAssertFalse(deskSizeMatches("11x17", key: "17x22"))
        XCTAssertTrue(deskSizeMatches("Set of two", key: "two"))
        XCTAssertTrue(deskSizeMatches("3 panels", key: "three"))
        XCTAssertFalse(deskSizeMatches("two", key: "three"))
    }
}
