import XCTest
@testable import TecopaKit

final class MultipartTests: XCTestCase {
    func testTwoFieldsAndOneFileAreTheExpectedBytes() throws {
        var form = Multipart(boundary: "XX")
        try form.field("region_id", "lassen_ca")
        try form.field("title", "Lassen: the peak")
        try form.file("files", filename: "day one.gpx", Data("<gpx/>\n".utf8))

        XCTAssertEqual(form.contentType, "multipart/form-data; boundary=XX")
        let expected = "--XX\r\n"
            + "Content-Disposition: form-data; name=\"region_id\"\r\n"
            + "\r\n"
            + "lassen_ca\r\n"
            + "--XX\r\n"
            + "Content-Disposition: form-data; name=\"title\"\r\n"
            + "\r\n"
            + "Lassen: the peak\r\n"
            + "--XX\r\n"
            + "Content-Disposition: form-data; name=\"files\"; filename=\"day one.gpx\"\r\n"
            + "Content-Type: application/octet-stream\r\n"
            + "\r\n"
            + "<gpx/>\n\r\n"
            + "--XX--\r\n"
        XCTAssertEqual(form.body(), Data(expected.utf8))
    }

    func testAFilesBytesAreNotChanged() throws {
        // a PNG is not UTF-8, and it has its own CR and LF bytes
        let bytes = Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0xFF])
        var form = Multipart(boundary: "XX")
        try form.file("file", filename: "poster.png", bytes)
        let head = "--XX\r\nContent-Disposition: form-data; name=\"file\"; filename=\"poster.png\"\r\n"
            + "Content-Type: application/octet-stream\r\n\r\n"
        XCTAssertEqual(form.body(), Data(head.utf8) + bytes + Data("\r\n--XX--\r\n".utf8))
    }

    func testAnEmptyFormIsOnlyTheClosingLine() {
        XCTAssertEqual(Multipart(boundary: "XX").body(), Data("--XX--\r\n".utf8))
    }

    func testTheDefaultBoundaryIsNewForEachForm() {
        let first = Multipart()
        let second = Multipart()
        XCTAssertTrue(first.boundary.hasPrefix("tecopa-"), first.boundary)
        XCTAssertNotEqual(first.boundary, second.boundary)
        XCTAssertEqual(first.contentType, "multipart/form-data; boundary=" + first.boundary)
    }

    func testAQuoteOrALineEndInANameIsAUsageFailure() {
        // each of these would end the header early, or add a second header
        for bad in ["a\"b", "a\rb", "a\nb", "a\r\nContent-Type: text/html"] {
            var form = Multipart(boundary: "XX")
            XCTAssertThrowsError(try form.field(bad, "value"), bad) { error in
                XCTAssertEqual((error as? TecopaFailure)?.kind, .usage, bad)
            }
            XCTAssertThrowsError(try form.file(bad, filename: "a.gpx", Data()), bad) { error in
                XCTAssertEqual((error as? TecopaFailure)?.kind, .usage, bad)
            }
            XCTAssertThrowsError(try form.file("files", filename: bad, Data()), bad) { error in
                XCTAssertEqual((error as? TecopaFailure)?.kind, .usage, bad)
            }
            // a refused part adds nothing to the form
            XCTAssertEqual(form.body(), Data("--XX--\r\n".utf8), bad)
        }
    }

    func testABackslashInANameIsAUsageFailure() {
        // python-multipart reads `\"` as a quote inside the name, so the engine would
        // read another name than the one the tool wrote
        for bad in ["a\\b", "a\\", "\\", "title\\\"; filename=\\"] {
            var form = Multipart(boundary: "XX")
            XCTAssertThrowsError(try form.field(bad, "value"), bad) { error in
                XCTAssertEqual((error as? TecopaFailure)?.kind, .usage, bad)
            }
            XCTAssertThrowsError(try form.file(bad, filename: "a.gpx", Data()), bad) { error in
                XCTAssertEqual((error as? TecopaFailure)?.kind, .usage, bad)
            }
            XCTAssertThrowsError(try form.file("files", filename: bad, Data()), bad) { error in
                XCTAssertEqual((error as? TecopaFailure)?.kind, .usage, bad)
            }
            XCTAssertEqual(form.body(), Data("--XX--\r\n".utf8), bad)
        }
    }

    func testAnEmptyNameIsAUsageFailure() {
        var form = Multipart(boundary: "XX")
        XCTAssertThrowsError(try form.field("", "value")) { error in
            XCTAssertEqual(error as? TecopaFailure,
                           TecopaFailure(.usage, "A form field name cannot be empty."))
        }
        XCTAssertThrowsError(try form.file("", filename: "a.gpx", Data())) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .usage)
        }
        XCTAssertThrowsError(try form.file("files", filename: "", Data([1]))) { error in
            XCTAssertEqual(error as? TecopaFailure, TecopaFailure(.usage, "A file name cannot be empty."))
        }
        XCTAssertEqual(form.body(), Data("--XX--\r\n".utf8))
        // an empty value is a value
        XCTAssertNoThrow(try form.field("title", ""))
    }

    func testAValueMayHoldAQuoteABackslashAndALineEnd() throws {
        // a value is in the body of its part, not in a header
        var form = Multipart(boundary: "XX")
        try form.field("subtitle", "the \"long\" way\r\nhome \\ away")
        let expected = "--XX\r\nContent-Disposition: form-data; name=\"subtitle\"\r\n\r\n"
            + "the \"long\" way\r\nhome \\ away\r\n--XX--\r\n"
        XCTAssertEqual(form.body(), Data(expected.utf8))
    }
}
