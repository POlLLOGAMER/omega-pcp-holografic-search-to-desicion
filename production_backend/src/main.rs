use ark_ff::{Fp64, MontBackend, MontConfig, PrimeField, Zero};
use ark_poly::{domain::EvaluationDomain, GeneralEvaluationDomain};
use ark_serialize::CanonicalSerialize;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{env, fs, path::Path};
use thiserror::Error;

const MODULUS: u64 = 2_013_265_921;

#[derive(MontConfig)]
#[modulus = "2013265921"]
#[generator = "31"]
pub struct FieldConfig;

type F = Fp64<MontBackend<FieldConfig, 1>>;

#[derive(Debug, Error)]
enum BackendError {
    #[error("uso: production_backend build <input.json> <proof.json> | verify <input.json> <proof.json> [row]")]
    Usage,
    #[error("IO: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("campo: {0}")]
    Field(String),
    #[error("prueba inválida: {0}")]
    InvalidProof(String),
}

#[derive(Debug, Deserialize)]
struct InputConstraint {
    a: Vec<(usize, u64)>,
    b: Vec<(usize, u64)>,
    c: Vec<(usize, u64)>,
}

#[derive(Debug, Deserialize)]
struct InputInstance {
    witness: Vec<u64>,
    constraints: Vec<InputConstraint>,
}

#[derive(Debug, Serialize, Deserialize)]
struct ProofFile {
    scheme: String,
    backend: String,
    field_modulus: u64,
    witness_len: usize,
    base_size: usize,
    extension_factor: usize,
    base_values: Vec<String>,
    extended_values: Vec<String>,
    merkle_root: String,
}

fn next_power_of_two(value: usize) -> usize {
    value.max(1).next_power_of_two()
}

fn parse_field(value: u64) -> Result<F, BackendError> {
    if value >= MODULUS {
        return Err(BackendError::Field(format!("valor {value} fuera de F_p")));
    }
    Ok(F::from(value))
}

fn field_string(value: F) -> String {
    value.into_bigint().to_string()
}

fn parse_field_string(value: &str) -> Result<F, BackendError> {
    let parsed = value
        .parse::<u64>()
        .map_err(|err| BackendError::Field(format!("valor no decimal {value}: {err}")))?;
    parse_field(parsed)
}

fn canonical_hash(value: &F) -> [u8; 32] {
    let mut encoded = Vec::new();
    value
        .serialize_compressed(&mut encoded)
        .expect("serialización de campo debe ser infalible");
    Sha256::digest(encoded).into()
}

fn hash_pair(left: &[u8; 32], right: &[u8; 32]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(left);
    hasher.update(right);
    hasher.finalize().into()
}

fn merkle_root(values: &[F]) -> [u8; 32] {
    if values.is_empty() {
        return Sha256::digest([]).into();
    }
    let mut level: Vec<[u8; 32]> = values.iter().map(canonical_hash).collect();
    while level.len() > 1 {
        let mut next = Vec::with_capacity((level.len() + 1) / 2);
        let mut index = 0;
        while index < level.len() {
            let right = level.get(index + 1).unwrap_or(&level[index]);
            next.push(hash_pair(&level[index], right));
            index += 2;
        }
        level = next;
    }
    level[0]
}

fn hex_root(root: &[u8; 32]) -> String {
    hex::encode(root)
}

fn build_lde(
    witness: &[F],
    extension_factor: usize,
) -> Result<(usize, Vec<F>, Vec<F>), BackendError> {
    if extension_factor == 0 || !extension_factor.is_power_of_two() {
        return Err(BackendError::Field(
            "extension_factor debe ser potencia de 2".into(),
        ));
    }
    let base_size = next_power_of_two(witness.len());
    let extended_size = base_size
        .checked_mul(extension_factor)
        .ok_or_else(|| BackendError::Field("dominio extendido demasiado grande".into()))?;
    let base_domain = GeneralEvaluationDomain::<F>::new(base_size).ok_or_else(|| {
        BackendError::Field(format!("no existe dominio base de tamaño {base_size}"))
    })?;
    let extended_domain = GeneralEvaluationDomain::<F>::new(extended_size).ok_or_else(|| {
        BackendError::Field(format!(
            "no existe dominio extendido de tamaño {extended_size}"
        ))
    })?;

    let mut padded = witness.to_vec();
    padded.resize(base_size, F::zero());
    let base_values = padded.clone();
    base_domain.ifft_in_place(&mut padded);
    extended_domain.fft_in_place(&mut padded);
    Ok((base_size, base_values, padded))
}

fn linear_eval(terms: &[(usize, u64)], witness: &[F]) -> Result<F, BackendError> {
    let mut value = F::zero();
    for (index, coefficient) in terms {
        let coordinate = witness.get(*index).ok_or_else(|| {
            BackendError::Field(format!("índice de witness fuera de rango: {index}"))
        })?;
        value += *coordinate * parse_field(*coefficient)?;
    }
    Ok(value)
}

fn row_residual(row: &InputConstraint, witness: &[F]) -> Result<F, BackendError> {
    Ok(
        linear_eval(&row.a, witness)? * linear_eval(&row.b, witness)?
            - linear_eval(&row.c, witness)?,
    )
}

fn build(input_path: &Path, proof_path: &Path) -> Result<(), BackendError> {
    let input: InputInstance = serde_json::from_slice(&fs::read(input_path)?)?;
    let witness: Vec<F> = input
        .witness
        .iter()
        .map(|value| parse_field(*value))
        .collect::<Result<_, _>>()?;
    for (row, constraint) in input.constraints.iter().enumerate() {
        let residual = row_residual(constraint, &witness)?;
        if !residual.is_zero() {
            return Err(BackendError::InvalidProof(format!(
                "fila {row} no satisfecha"
            )));
        }
    }
    let extension_factor = 4;
    let (base_size, base_values, extended_values) = build_lde(&witness, extension_factor)?;
    let proof = ProofFile {
        scheme: "witness-lde-merkle-v1".into(),
        backend: "arkworks-rs/algebra@57be20e56a142b059bca05653961f8a9ca4f54ae".into(),
        field_modulus: MODULUS,
        witness_len: witness.len(),
        base_size,
        extension_factor,
        base_values: base_values.iter().copied().map(field_string).collect(),
        extended_values: extended_values.iter().copied().map(field_string).collect(),
        merkle_root: hex_root(&merkle_root(&extended_values)),
    };
    fs::write(proof_path, serde_json::to_vec_pretty(&proof)?)?;
    println!("proof written to {}", proof_path.display());
    println!(
        "scheme={}, base_size={}, extended_size={}, commitment={}",
        proof.scheme,
        proof.base_size,
        proof.extended_values.len(),
        proof.merkle_root
    );
    Ok(())
}

fn verify(input_path: &Path, proof_path: &Path, row: usize) -> Result<(), BackendError> {
    let input: InputInstance = serde_json::from_slice(&fs::read(input_path)?)?;
    let proof: ProofFile = serde_json::from_slice(&fs::read(proof_path)?)?;
    if proof.field_modulus != MODULUS || proof.scheme != "witness-lde-merkle-v1" {
        return Err(BackendError::InvalidProof(
            "esquema o campo incompatibles".into(),
        ));
    }
    if proof.witness_len != input.witness.len()
        || proof.base_size != next_power_of_two(input.witness.len())
    {
        return Err(BackendError::InvalidProof(
            "longitud de witness/base incompatible".into(),
        ));
    }
    let witness: Vec<F> = input
        .witness
        .iter()
        .map(|v| parse_field(*v))
        .collect::<Result<_, _>>()?;
    let (base_size, expected_base, expected_extended) =
        build_lde(&witness, proof.extension_factor)?;
    if base_size != proof.base_size {
        return Err(BackendError::InvalidProof("base_size inconsistente".into()));
    }
    let supplied_base: Vec<F> = proof
        .base_values
        .iter()
        .map(|v| parse_field_string(v))
        .collect::<Result<_, _>>()?;
    let supplied_extended: Vec<F> = proof
        .extended_values
        .iter()
        .map(|v| parse_field_string(v))
        .collect::<Result<_, _>>()?;
    if supplied_base != expected_base || supplied_extended != expected_extended {
        return Err(BackendError::InvalidProof(
            "evaluaciones LDE inconsistentes".into(),
        ));
    }
    if hex_root(&merkle_root(&supplied_extended)) != proof.merkle_root {
        return Err(BackendError::InvalidProof("Merkle root inválida".into()));
    }
    let local_ok = input
        .constraints
        .get(row)
        .map(|constraint| row_residual(constraint, &witness).map(|value| value.is_zero()))
        .transpose()?
        .unwrap_or(true);
    if !local_ok {
        return Err(BackendError::InvalidProof(format!("fila {row} rechazada")));
    }
    println!("accepted=true row={} commitment={}", row, proof.merkle_root);
    Ok(())
}

fn run() -> Result<(), BackendError> {
    let args: Vec<String> = env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("build") if args.len() == 4 => build(Path::new(&args[2]), Path::new(&args[3])),
        Some("verify") if (args.len() == 4 || args.len() == 5) => {
            let row = args
                .get(4)
                .map(|value| value.parse::<usize>())
                .transpose()
                .map_err(|err| BackendError::Field(err.to_string()))?
                .unwrap_or(0);
            verify(Path::new(&args[2]), Path::new(&args[3]), row)
        }
        _ => Err(BackendError::Usage),
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("error: {error}");
        std::process::exit(1);
    }
}
