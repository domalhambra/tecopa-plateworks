import Foundation

/// One multipart/form-data body, in the RFC 7578 form that the engine's routes read.
/// The tool sends each value and each file's bytes unchanged.
public struct Multipart: Sendable {
    /// The line that divides the parts. A test gives its own, so the bytes of a body
    /// are known. The default is new for each form, so no value can contain it.
    public let boundary: String
    private var parts: [Part] = []

    private struct Part: Sendable {
        let name: String
        let filename: String?
        let data: Data
    }

    public init(boundary: String = "tecopa-" + UUID().uuidString) {
        self.boundary = boundary
    }

    /// The value of the request's Content-Type header.
    public var contentType: String { "multipart/form-data; boundary=\(boundary)" }

    /// Add one form field. The value can be any text: it is in the body of its part.
    public mutating func field(_ name: String, _ value: String) throws {
        try Self.check(name, "A form field name")
        parts.append(Part(name: name, filename: nil, data: Data(value.utf8)))
    }

    /// Add one file. A route that takes several files gets one part for each, all
    /// with the same name.
    public mutating func file(_ name: String, filename: String, _ data: Data) throws {
        try Self.check(name, "A form field name")
        try Self.check(filename, "A file name")
        parts.append(Part(name: name, filename: filename, data: data))
    }

    public func body() -> Data {
        var out = Data()
        for part in parts {
            var head = "--\(boundary)\r\nContent-Disposition: form-data; name=\"\(part.name)\""
            if let filename = part.filename {
                head += "; filename=\"\(filename)\"\r\nContent-Type: application/octet-stream"
            }
            out.append(Data((head + "\r\n\r\n").utf8))
            out.append(part.data)
            out.append(Data("\r\n".utf8))
        }
        out.append(Data("--\(boundary)--\r\n".utf8))
        return out
    }

    /// A name goes into a header between quotes. A quote would end it early, and a
    /// line end would start a new header, so the encoder never writes one.
    ///
    /// The check reads bytes: to Swift, CR and LF together are one character, and a
    /// search for either one alone does not find it.
    private static func check(_ text: String, _ what: String) throws {
        let bad: Set<UInt8> = [0x22, 0x0D, 0x0A]      // the quote, CR, LF
        guard !text.utf8.contains(where: bad.contains) else {
            throw TecopaFailure(
                .usage, "\(what) cannot contain a quote or a line end: \(text.debugDescription)")
        }
    }
}
