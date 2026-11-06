import Foundation
import TecopaKit

/// The app's start and quit decisions, kept free of AppKit so they are tested
/// (phase 1 spec 5.5, plan task 17).

enum StartAction: Equatable { case adopt, refuseForeign, refuseNotAnswering, spawn }

func startAction(_ state: EngineHost.PortState) -> StartAction {
    switch state {
    case .adopt: return .adopt
    case .foreign: return .refuseForeign
    case .busy: return .refuseNotAnswering
    case .none: return .spawn
    }
}

enum QuitAnswer: Equatable { case now, stopWithoutConfirm, readJobsFirst, alreadyWaiting }

/// One quit request gets an answer that reads the jobs; a second one, while the
/// first waits, gets `.alreadyWaiting`, so the app replies to the system once.
struct QuitGate {
    private(set) var isQuitting = false

    mutating func answer(ownsEngine: Bool, forced: Bool) -> QuitAnswer {
        guard !isQuitting else { return .alreadyWaiting }
        guard ownsEngine else { return .now }
        isQuitting = true
        return forced ? .stopWithoutConfirm : .readJobsFirst
    }

    mutating func cancel() { isQuitting = false }
}

enum AfterJobs: Equatable { case stopEngine, confirm(jobs: Int?) }

/// `.unknown` means the engine could not be asked: it is not up yet, so nothing
/// it runs can be lost (Review Focus 5).
func afterJobs(_ read: JobsRead) -> AfterJobs {
    switch read {
    case .active(0), .unknown: return .stopEngine
    case .active(let n): return .confirm(jobs: n)
    case .timedOut: return .confirm(jobs: nil)
    }
}

/// A line for the log when the app adopts an engine it did not start, and that
/// engine is not this bundle's build (Review Focus 1).
func adoptNote(bundleVersion: String, engineVersion: String?) -> String? {
    let found = engineVersion ?? "unknown"
    guard found != bundleVersion else { return nil }
    return "event=adopt.version_mismatch bundle=\(bundleVersion) engine=\(found): the engine on 8848 is not this app's build"
}

/// The marker `tecopa engine stop --force` leaves: a quit within 15 s of it
/// skips the confirm (spec section 13).
func quitMarkerIsFresh(modified: Date?, now: Date) -> Bool {
    guard let modified else { return false }
    let age = now.timeIntervalSince(modified)
    return age >= 0 && age < 15
}
