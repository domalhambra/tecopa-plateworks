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

    func testIntValueIsNilForANumberThatIsNotAnInt() {
        // a JSON number past Int64 decodes as a double; Int(d) would trap on it
        XCTAssertNil(JSONValue.double(1e19).intValue)
        XCTAssertNil(JSONValue.double(1.5).intValue)
        XCTAssertEqual(JSONValue.double(8848).intValue, 8848)
    }

    func testAnEmptyRepoFlagFailsAndDoesNotFallThrough() {
        XCTAssertThrowsError(try RepoLocator.resolve(flag: "", env: ["TECOPA_REPO": "/good/env"],
                                                     baked: "/good/baked", fileExists: exists)) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
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

    func testTheRepoPathIsStandardized() throws {
        for given in ["/good/x//", "/good/x/.", "/good//x", "/good/y/../x", "/good/x"] {
            let repo = try RepoLocator.resolve(flag: given, env: [:], baked: nil, fileExists: exists)
            XCTAssertEqual(repo, "/good/x", given)
        }
    }

    func testARelativeRepoPathBecomesAbsolute() throws {
        // a script runs with the repo as its working directory, so the path must
        // not depend on where the tool itself was started
        let repo = try RepoLocator.resolve(flag: "some/checkout", env: [:], baked: nil,
                                           fileExists: { _ in true })
        XCTAssertTrue(repo.hasPrefix("/"), repo)
        XCTAssertTrue(repo.hasSuffix("/some/checkout"), repo)
    }

    func testAnEmptyRepoFlagIsNeverTheCurrentDirectory() {
        // standardized, an empty path would be the folder the tool was started in
        XCTAssertThrowsError(try RepoLocator.resolve(flag: "", env: [:], baked: nil,
                                                     fileExists: { _ in true })) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
    }

    func testNoPathAtAllIsAnEnvironmentFault() {
        XCTAssertThrowsError(try RepoLocator.resolve(flag: nil, env: [:], baked: nil, fileExists: exists)) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
    }
}
