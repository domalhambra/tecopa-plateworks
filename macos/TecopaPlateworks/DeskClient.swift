import Foundation
import Security

/// Reads an order's paid size from the order desk (phase 2 spec, decisions 8 and 9).
/// It only reads: GET https://lab.plateworks.org/desk/data with the desk's bearer token
/// from the login Keychain. It never taps the desk and never sends anything.
enum DeskClient {
    static let service = "plateworks-lab-desk-api-token"
    static let account = "dom"
    static let url = URL(string: "https://lab.plateworks.org/desk/data")!

    struct Failure: Error { let message: String }

    static func order(_ number: String) async -> Result<DeskOrder?, Failure> {
        guard let token = Keychain.read(service: service, account: account), !token.isEmpty else {
            return .failure(Failure(message: "Paid size: not connected (add the desk token in Settings)."))
        }
        var req = URLRequest(url: url, timeoutInterval: 15)
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        do {
            let (data, response) = try await URLSession.shared.data(for: req)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard status == 200 else {
                return .failure(Failure(message: status == 401
                    ? "The order desk refused the token (401). Check it in Settings."
                    : "The order desk answered \(status)."))
            }
            return .success(DeskOrder.find(number, in: data))
        } catch {
            return .failure(Failure(message: "The order desk could not be reached: \(error.localizedDescription)"))
        }
    }
}

/// The login Keychain, for the one secret the app keeps (the workspace rule: secrets
/// in the Keychain, never in a file).
enum Keychain {
    static func read(service: String, account: String) -> String? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                kSecAttrService as String: service, kSecAttrAccount as String: account,
                                kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    @discardableResult
    static func write(_ value: String, service: String, account: String) -> Bool {
        let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                   kSecAttrService as String: service, kSecAttrAccount as String: account]
        SecItemDelete(base as CFDictionary)
        guard !value.isEmpty else { return true }
        var add = base
        add[kSecValueData as String] = Data(value.utf8)
        return SecItemAdd(add as CFDictionary, nil) == errSecSuccess
    }
}
