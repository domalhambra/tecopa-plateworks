import XCTest
@testable import TecopaKit

final class ValueTests: XCTestCase {
    func testJSONRoundTripKeepsIntegersAndNesting() throws {
        let text = #"{"a":1,"b":1.5,"c":"x","d":[true,null],"e":{"f":2}}"#
        let value = try JSONValue.parse(Data(text.utf8))
        XCTAssertEqual(value["a"], .int(1))
        XCTAssertEqual(value["b"], .double(1.5))
        XCTAssertEqual(value["c"]?.stringValue, "x")
        XCTAssertEqual(value["d"], .array([.bool(true), .null]))
        XCTAssertEqual(value["e"]?["f"]?.intValue, 2)
        XCTAssertEqual(value.text(pretty: false), text)
    }

    func testFailureMapsEachKindToItsExitCode() {
        XCTAssertEqual(TecopaFailure(.refused, "x").exitCode, 1)
        XCTAssertEqual(TecopaFailure(.usage, "x").exitCode, 2)
        XCTAssertEqual(TecopaFailure(.engineUnreachable, "x").exitCode, 3)
        XCTAssertEqual(TecopaFailure(.environment, "x").exitCode, 4)
    }

    func testFailureEnvelopeCarriesTheEngineBody() {
        let f = TecopaFailure(.refused, "no", hint: "try", status: 422,
                              body: .object(["detail": .string("zoom cap")]))
        let e = f.json
        XCTAssertEqual(e["ok"], .bool(false))
        XCTAssertEqual(e["error"]?["kind"]?.stringValue, "refused")
        XCTAssertEqual(e["error"]?["hint"]?.stringValue, "try")
        XCTAssertEqual(e["error"]?["status"]?.intValue, 422)
        XCTAssertEqual(e["error"]?["body"]?["detail"]?.stringValue, "zoom cap")
    }

    func testSuccessEnvelope() {
        XCTAssertEqual(envelope(.int(3)), .object(["ok": .bool(true), "data": .int(3)]))
    }

    private let exists: (String) -> Bool = { $0.hasPrefix("/good/") }

    func testRepoFlagWinsOverVariableAndBakedPath() throws {
        let repo = try RepoLocator.resolve(flag: "/good/flag", env: ["TECOPA_REPO": "/good/env"],
                                           baked: "/good/baked", fileExists: exists)
        XCTAssertEqual(repo, "/good/flag")
    }

    func testRepoVariableWinsOverBakedPath() throws {
        let repo = try RepoLocator.resolve(flag: nil, env: ["TECOPA_REPO": "/good/env/"],
                                           baked: "/good/baked", fileExists: exists)
        XCTAssertEqual(repo, "/good/env")
    }

    func testRepoFallsBackToTheBakedPath() throws {
        let repo = try RepoLocator.resolve(flag: nil, env: [:], baked: "/good/baked", fileExists: exists)
        XCTAssertEqual(repo, "/good/baked")
    }

    func testAWrongFlagFailsAndDoesNotFallThrough() {
        // an explicit wrong path must be an error, never a silent use of another repo
        XCTAssertThrowsError(try RepoLocator.resolve(flag: "/bad/flag", env: [:],
                                                     baked: "/good/baked", fileExists: exists)) { error in
            let f = error as? TecopaFailure
            XCTAssertEqual(f?.kind, .environment)
            XCTAssertTrue(f?.message.contains("/bad/flag") ?? false)
            XCTAssertTrue(f?.message.contains("--repo") ?? false)
        }
    }

    func testNoPathAtAllIsAnEnvironmentFault() {
        XCTAssertThrowsError(try RepoLocator.resolve(flag: nil, env: [:], baked: nil, fileExists: exists)) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
    }
}
