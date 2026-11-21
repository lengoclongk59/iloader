//! Headless helper for the cli-anything-iloader harness.
//!
//! Mirrors the Tauri commands in `src-tauri/src` (account, device, sideload)
//! without any GUI dependency. Every command prints exactly one JSON document
//! to stdout: `{"ok": true, "data": ...}` or `{"ok": false, "error": "..."}`.
//!
//! Secrets are never accepted on argv: the Apple ID password is read from the
//! `ILOADER_PASSWORD` environment variable, and the 2FA code from
//! `ILOADER_2FA_CODE` (or stdin when unset).
//!
//! With `--use-saved-login` the password is instead read from the OS keyring
//! entry the iloader GUI writes (service `iloader`, user = email). The helper
//! keeps its own anisette identity under `--data-dir` (sharing the GUI's made Apple reject
//! the login with -22410) and reuses the GUI's signing certificate through a read-only view
//! of its keyring storage, so it can never overwrite the GUI's certificate key.
//!
//! `--2fa-file <path>` (or `ILOADER_2FA_FILE`) makes the helper wait (up to 3 minutes) for a file to
//! appear holding the 2FA code, which is deleted after reading. This lets a
//! caller without an interactive stdin supply the code once Apple sends it.

use std::{
    path::{Path, PathBuf},
    process::ExitCode,
    time::{Duration, Instant},
};

use keyring::Entry;

use idevice::{
    IdeviceService,
    lockdown::LockdownClient,
    usbmuxd::{Connection, UsbmuxdAddr, UsbmuxdConnection},
};
use isideload::{
    anisette::{AnisetteClientInfo, remote_v3::RemoteV3AnisetteProvider},
    auth::apple_account::{AppleAccount, TwoFactorCallbackParams, TwoFactorCallbackResponse},
    dev::{
        app_ids::AppIdsApi, certificates::CertificatesApi, developer_session::DeveloperSession,
    },
    sideload::{
        SideloaderBuilder,
        builder::{ExtensionsBehavior, ExtensionsBehaviorSelection, MaxCertsBehavior},
        sideloader::Sideloader,
    },
    util::{
        callbacks::{ExtensionsBehaviorCallbackBox, MaxCertsCallbackBox},
        fs_storage::FsStorage,
        keyring_storage::KeyringStorage,
        storage::SideloadingStorage,
    },
};
use rootcause::prelude::*;
use serde_json::{Value, json};

const DEFAULT_ANISETTE: &str = "ani.iloader.app";

type Sl = Sideloader<MaxCertsCallbackBox, ExtensionsBehaviorCallbackBox>;

struct Args {
    cmd: String,
    positional: Vec<String>,
    email: Option<String>,
    anisette: String,
    data_dir: PathBuf,
    udid: Option<String>,
    use_saved_login: bool,
    tfa_file: Option<PathBuf>,
}

fn parse_args() -> Result<Args, String> {
    let mut it = std::env::args().skip(1);
    let cmd = it.next().ok_or("missing command")?;
    let mut a = Args {
        cmd,
        positional: vec![],
        email: None,
        anisette: DEFAULT_ANISETTE.into(),
        // Anisette identity and certificate must outlive temp cleanups.
        data_dir: std::env::var_os("ILOADER_CLI_HOME")
            .map(|home| PathBuf::from(home).join("helper"))
            .or_else(|| {
                std::env::var_os("USERPROFILE")
                    .or_else(|| std::env::var_os("HOME"))
                    .map(|home| {
                        PathBuf::from(home)
                            .join(".cli-anything-iloader")
                            .join("helper")
                    })
            })
            .unwrap_or_else(|| std::env::temp_dir().join("iloader-cli")),
        udid: None,
        use_saved_login: false,
        tfa_file: std::env::var_os("ILOADER_2FA_FILE").map(PathBuf::from),
    };
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--email" => a.email = it.next(),
            "--anisette" => a.anisette = it.next().ok_or("--anisette needs a value")?,
            "--data-dir" => a.data_dir = it.next().ok_or("--data-dir needs a value")?.into(),
            "--udid" => a.udid = it.next(),
            "--use-saved-login" => a.use_saved_login = true,
            "--2fa-file" => a.tfa_file = it.next().map(PathBuf::from),
            _ => a.positional.push(arg),
        }
    }
    Ok(a)
}

/// Read-only view of the GUI's keyring storage (service `iloader`).
///
/// The sideloader only ever writes one thing here, the certificate private key, and it does so
/// when it cannot find one. Refusing every write guarantees the helper can never replace the
/// key the GUI's certificate depends on.
struct ReadOnlyKeyringStorage {
    inner: KeyringStorage,
}

impl SideloadingStorage for ReadOnlyKeyringStorage {
    fn store(&self, key: &str, _value: &str) -> Result<(), Report> {
        Err(report!(
            "refusing to write {key} to the GUI keyring storage"
        ))
    }

    fn retrieve(&self, key: &str) -> Result<Option<String>, Report> {
        self.inner.retrieve(key)
    }

    fn store_data(&self, key: &str, _value: &[u8]) -> Result<(), Report> {
        Err(report!(
            "refusing to write {key} to the GUI keyring storage"
        ))
    }

    fn retrieve_data(&self, key: &str) -> Result<Option<Vec<u8>>, Report> {
        self.inner.retrieve_data(key)
    }

    fn delete(&self, key: &str) -> Result<(), Report> {
        Err(report!(
            "refusing to delete {key} from the GUI keyring storage"
        ))
    }
}

/// Waits up to three minutes for `path` to appear, then returns its contents and deletes it.
async fn wait_for_code_file(path: &Path) -> Result<String, Report> {
    let deadline: Instant = Instant::now() + Duration::from_secs(180);
    while Instant::now() < deadline {
        if let Ok(code) = std::fs::read_to_string(path) {
            if !code.trim().is_empty() {
                std::fs::remove_file(path)?;
                return Ok(code);
            }
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    Err(report!("timed out waiting for the 2FA code file"))
}

async fn login(a: &Args) -> Result<Sl, String> {
    let email = a
        .email
        .clone()
        .ok_or("--email is required for this command")?;
    let password: String = if a.use_saved_login {
        // Same entry the GUI's `login_stored` command reads; never printed or logged.
        Entry::new("iloader", &email)
            .and_then(|entry| entry.get_password())
            .map_err(|e| format!("no saved iloader login for {email} in the keyring: {e}"))?
    } else {
        std::env::var("ILOADER_PASSWORD").map_err(|_| "ILOADER_PASSWORD is not set".to_string())?
    };
    std::fs::create_dir_all(&a.data_dir).map_err(|e| e.to_string())?;

    let tfa_file: Option<PathBuf> = a.tfa_file.clone();
    let tfa = move |_params: TwoFactorCallbackParams| {
        let tfa_file = tfa_file.clone();
        Box::pin(async move {
            let code = match (std::env::var("ILOADER_2FA_CODE"), tfa_file) {
                (Ok(c), _) => c,
                (Err(_), Some(path)) => wait_for_code_file(&path).await?,
                (Err(_), None) => {
                    let mut line = String::new();
                    std::io::stdin().read_line(&mut line)?;
                    line
                }
            };
            Ok(TwoFactorCallbackResponse::SubmitCode(
                code.trim().to_string(),
            ))
        }) as std::pin::Pin<Box<dyn std::future::Future<Output = Result<_, Report>> + Send>>
    };

    let url = if a.anisette.starts_with("http") {
        a.anisette.clone()
    } else {
        format!("https://{}", a.anisette)
    };
    let storage = || Box::new(FsStorage::new(a.data_dir.clone()));
    // Mirror the GUI's client info override (see `account.rs` in src-tauri).
    let client_info = AnisetteClientInfo {
        client_info: "<MacBookPro13,3> <Mac OS X;10.12.6;16G29> \
                      <com.apple.AuthKit/1 (com.apple.akd/1.0)>"
            .to_string(),
        user_agent: "akd/1.0 CFNetwork/811.5.4 Darwin/16.7.0".to_string(),
    };
    let mut account = AppleAccount::builder(&email.to_lowercase())
        .anisette_provider(
            RemoteV3AnisetteProvider::default()
                .map_err(|e| format!("{e:?}"))?
                .set_serial_number("0".to_string())
                .set_storage(storage())
                .set_client_info_override(Some(client_info))
                .set_url(&url),
        )
        .login(&password, Box::new(tfa))
        .await
        .map_err(|e| format!("login failed: {e:?}"))?;
    let dev = DeveloperSession::from_account(&mut account)
        .await
        .map_err(|e| format!("developer session failed: {e:?}"))?;

    // Headless: never revoke certificates silently; abort instead.
    let max_certs: MaxCertsCallbackBox = Box::new(|_certs| Box::pin(async { Ok(None) }));
    // With the saved login, reuse the GUI's certificate (machine name "iloader", key in its
    // keyring) read-only instead of creating a second one, which free accounts cannot afford.
    let (machine_name, cert_storage): (&str, Box<dyn SideloadingStorage>) = if a.use_saved_login {
        (
            "iloader",
            Box::new(ReadOnlyKeyringStorage {
                inner: KeyringStorage::new("iloader".to_string()),
            }),
        )
    } else {
        ("iloader-cli", Box::new(FsStorage::new(a.data_dir.clone())))
    };
    Ok(SideloaderBuilder::new(dev, email.to_lowercase())
        .machine_name(machine_name.into())
        .storage(cert_storage)
        .extensions_behavior(ExtensionsBehaviorSelection::Fixed(
            ExtensionsBehavior::ReuseMain,
        ))
        .max_certs_behavior(MaxCertsBehavior::Prompt(max_certs))
        .build())
}

async fn list_devices() -> Result<Value, String> {
    let mut mux = UsbmuxdConnection::default()
        .await
        .map_err(|e| format!("Failed to connect to usbmuxd: {e}"))?;
    let devs = mux
        .get_devices()
        .await
        .map_err(|e| format!("Failed to list devices: {e}"))?;
    let addr = UsbmuxdAddr::from_env_var().map_err(|e| e.to_string())?;
    let mut out = vec![];
    for d in devs {
        let conn = match d.connection_type {
            Connection::Usb => "USB",
            Connection::Network(_) => "Network",
            Connection::Unknown(_) => "Unknown",
        };
        let provider = d.to_provider(addr.clone(), "iloader-cli");
        let info = async {
            let mut lc = LockdownClient::connect(&provider)
                .await
                .map_err(|e| e.to_string())?;
            let name = lc
                .get_value(Some("DeviceName"), None)
                .await
                .map_err(|e| e.to_string())?;
            let ver = lc
                .get_value(Some("ProductVersion"), None)
                .await
                .map_err(|e| e.to_string())?;
            Ok::<_, String>((
                name.as_string().unwrap_or_default().to_string(),
                ver.as_string().unwrap_or_default().to_string(),
            ))
        }
        .await;
        out.push(match info {
            Ok((name, version)) => json!({
                "udid": d.udid, "id": d.device_id, "connectionType": conn,
                "name": name, "version": version}),
            Err(e) => json!({
                "udid": d.udid, "id": d.device_id, "connectionType": conn, "error": e}),
        });
    }
    Ok(json!(out))
}

async fn install(a: &Args) -> Result<Value, String> {
    let ipa = a.positional.first().ok_or("install needs an IPA path")?;
    let udid = a.udid.clone().ok_or("--udid is required")?;
    let mut mux = UsbmuxdConnection::default()
        .await
        .map_err(|e| e.to_string())?;
    let device = mux
        .get_device(&udid)
        .await
        .map_err(|e| format!("Failed to get device: {e}"))?;
    let provider = device.to_provider(
        UsbmuxdAddr::from_env_var().map_err(|e| e.to_string())?,
        "iloader-cli",
    );
    let mut pairing = mux
        .get_pair_record(&udid)
        .await
        .map_err(|e| format!("Failed to get pairing record: {e}"))?;
    pairing.udid = Some(udid.clone());
    let pairing_bytes = pairing.serialize().map_err(|e| e.to_string())?;
    let mut sl = login(a).await?;
    let special = sl
        .install_app(
            &provider,
            PathBuf::from(ipa),
            true,
            None::<fn(f32) -> std::future::Ready<()>>,
            Some(&pairing_bytes),
        )
        .await
        .map_err(|e| format!("install failed: {e:?}"))?;
    Ok(json!({"installed": ipa, "udid": udid, "special": special.is_some()}))
}

async fn account_cmd(a: &Args) -> Result<Value, String> {
    let mut sl = login(a).await?;
    let team = sl.get_team().await.map_err(|e| format!("{e:?}"))?;
    let dev = sl.get_dev_session();
    match a.cmd.as_str() {
        "certs" => {
            let certs = dev
                .list_all_development_certs(&team, None)
                .await
                .map_err(|e| format!("{e:?}"))?;
            Ok(json!(
                certs
                    .into_iter()
                    .map(|c| json!({
                        "name": c.name, "certificateId": c.certificate_id,
                        "serialNumber": c.serial_number, "machineName": c.machine_name,
                        "machineId": c.machine_id}))
                    .collect::<Vec<_>>()
            ))
        }
        "revoke-cert" => {
            let serial = a
                .positional
                .first()
                .ok_or("revoke-cert needs a serial number")?;
            dev.revoke_development_cert(&team, serial, None)
                .await
                .map_err(|e| format!("{e:?}"))?;
            Ok(json!({"revoked": serial}))
        }
        "app-ids" => {
            let r = dev
                .list_app_ids(&team, None)
                .await
                .map_err(|e| format!("{e:?}"))?;
            Ok(json!({
                "maxQuantity": r.max_quantity,
                "availableQuantity": r.available_quantity,
                "appIds": r.app_ids.iter().map(|x| json!({
                    "appIdId": x.app_id_id, "identifier": x.identifier, "name": x.name,
                })).collect::<Vec<_>>()}))
        }
        _ => {
            let id = a
                .positional
                .first()
                .ok_or("delete-app-id needs an app id id")?;
            dev.delete_app_id(&team, id, None)
                .await
                .map_err(|e| format!("{e:?}"))?;
            Ok(json!({"deleted": id}))
        }
    }
}

async fn run(a: &Args) -> Result<Value, String> {
    match a.cmd.as_str() {
        "devices" => list_devices().await,
        "install" => install(a).await,
        "certs" | "revoke-cert" | "app-ids" | "delete-app-id" => account_cmd(a).await,
        other => Err(format!("unknown command: {other}")),
    }
}

#[tokio::main]
async fn main() -> ExitCode {
    // Both `ring` and `aws-lc-rs` are in the dependency tree, so rustls cannot pick a default
    // provider itself and would panic when provisioning anisette over a websocket.
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("no other rustls CryptoProvider is installed this early in main");
    // Opt-in diagnostics: `RUST_LOG=isideload=debug` logs to stderr, never stdout.
    if std::env::var_os("RUST_LOG").is_some() {
        tracing_subscriber::fmt()
            .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
            .with_writer(std::io::stderr)
            .init();
    }
    let res = match parse_args() {
        Ok(a) => run(&a).await,
        Err(e) => Err(e),
    };
    match res {
        Ok(data) => {
            println!("{}", json!({"ok": true, "data": data}));
            ExitCode::SUCCESS
        }
        Err(e) => {
            println!("{}", json!({"ok": false, "error": e}));
            ExitCode::from(1)
        }
    }
}
