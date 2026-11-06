import Foundation

/// What the app reads back from an order's files and the order desk, to show it.
/// Display only: every decision is the engine's (phase 2 spec, decision 3).

struct PreviewSize: Identifiable, Equatable {
    var key: String
    var orientation: String
    var printIn: [Double]
    var offered: Bool
    var why: String?
    var warning: String?
    var id: String { key }

    var label: String {
        let name: String
        switch key {
        case "two": name = "Set of two"
        case "three": name = "Set of three"
        default: name = key.replacingOccurrences(of: "x", with: " × ")
        }
        guard printIn.count == 2 else { return name }
        func f(_ v: Double) -> String { v == v.rounded() ? String(Int(v)) : String(v) }
        return "\(name) (\(f(printIn[0])) × \(f(printIn[1])) in)"
    }

    /// The `sizes` of work/preview/preview.json, in the preview's order.
    static func parse(_ data: Data) -> [PreviewSize] {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let sizes = root["sizes"] as? [[String: Any]] else { return [] }
        return sizes.compactMap { e in
            guard let key = e["key"] as? String else { return nil }
            let warning = (e["warning"] as? String).flatMap { $0.isEmpty ? nil : $0 }
            return PreviewSize(key: key, orientation: e["orientation"] as? String ?? "",
                               printIn: (e["print_in"] as? [NSNumber])?.map(\.doubleValue) ?? [],
                               offered: e["offered"] as? Bool ?? false,
                               why: e["why"] as? String, warning: warning)
        }
    }

    static func load(folder: String) -> [PreviewSize] {
        let path = folder + "/work/preview/preview.json"
        guard let data = FileManager.default.contents(atPath: path) else { return [] }
        return parse(data)
    }
}

/// One Tecopa row of the order desk (GET /desk/data, records.tecopa).
struct DeskOrder: Equatable {
    var orderID: String
    var size: String
    var paid: Bool
    var status: String

    /// The row for `number` in a /desk/data answer, or nil when it has none.
    static func find(_ number: String, in data: Data) -> DeskOrder? {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let records = root["records"] as? [String: Any],
              let rows = records["tecopa"] as? [[String: Any]] else { return nil }
        func text(_ v: Any?) -> String {
            switch v {
            case let s as String: return s.trimmingCharacters(in: .whitespaces)
            case let n as NSNumber: return n.stringValue
            default: return ""
            }
        }
        guard let row = rows.first(where: { text($0["order_id"]) == number }) else { return nil }
        let paid = text(row["paid"])
        return DeskOrder(orderID: number, size: text(row["size"]),
                         paid: !paid.isEmpty && !["no", "false", "0"].contains(paid.lowercased()),
                         status: text(row["status"]))
    }
}

/// Whether the desk's size text names the preview's size key. Lenient: the desk is
/// typed by a form and by hand ("17x22", "17 × 22", "Set of two", "two panels").
func deskSizeMatches(_ desk: String, key: String) -> Bool {
    let d = desk.lowercased()
        .replacingOccurrences(of: "×", with: "x")
        .replacingOccurrences(of: " ", with: "")
        .replacingOccurrences(of: "in", with: "")
        .replacingOccurrences(of: "\"", with: "")
    switch key {
    case "two": return d.contains("two") || d.contains("2panel") || d == "2"
    case "three": return d.contains("three") || d.contains("3panel") || d == "3"
    default: return d.contains(key) || d.contains(key.split(separator: "x").reversed().joined(separator: "x"))
    }
}
