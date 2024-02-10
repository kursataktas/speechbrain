"""
Data preparation script for the GigaSpeech dataset.

Download instructions: https://github.com/SpeechColab/GigaSpeech
Reference: https://arxiv.org/abs/2106.06909

Author
-------
 * Adel Moumen, 2024
"""

import logging
import os
import json
import csv
from dataclasses import dataclass
import functools
from speechbrain.utils.parallel import parallel_map

logger = logging.getLogger(__name__)

GRABAGE_UTTERANCE_TAGS = ["<SIL>", "<MUSIC>", "<NOISE>", "<OTHER>"]
PUNCTUATION_TAGS = {
    "<COMMA>": ",",
    "<EXCLAMATIONPOINT>": "!",
    "<PERIOD>": ".",
    "<QUESTIONMARK>": "?",
}
SPLITS = ["DEV", "TEST"]
TRAIN_SUBSET = ["XS", "S", "M", "L", "XL"]


@dataclass
class GigaSpeechRow:
    """ Dataclass for handling GigaSpeech rows.

    Attributes
    ----------
    utt_id : str
        The segment ID.
    audio_id : str
        The audio ID.
    audio_path : str
        The path to the audio file.
    speaker : str
        The speaker ID.
    begin_time : float
        The start time of the segment.
    end_time : float
        The end time of the segment.
    duration : float
        The duration of the segment.
    text : str
        The text of the segment.
    """

    utt_id: str  # segment[sid]
    audio_id: str  # audio[aid]
    audio_path: str  # by default this is opus files
    speaker: str  # audio["speaker"]
    begin_time: float
    end_time: float
    duration: float
    text: str


def prepare_gigaspeech(
    data_folder: str,
    save_folder: str,
    splits: list,
    json_file: str = "GigaSpeech.json",
    skip_prep: bool = False,
) -> None:
    """ Prepare the csv files for GigaSpeech dataset.

    Download instructions: https://github.com/SpeechColab/GigaSpeech
    Reference: https://arxiv.org/abs/2106.06909

    The `train.csv` file is created by following the train subset specified in the `splits` list.
    It must be part of the `TRAIN_SUBSET` list. You cannot use multiple train subsets.

    The `dev.csv` and `test.csv` files are created based on the `DEV` and `TEST` splits
    specified in the `splits` list.

    Parameters
    ----------
    data_folder : str
        The path to the GigaSpeech dataset.
    save_folder : str
        The path to the folder where the CSV files will be saved.
    splits : list
        The list of splits to be used for creating the CSV files.
    json_file : str, optional
        The name of the JSON file containing the metadata of the GigaSpeech dataset.
    skip_prep : bool, optional
        If True, the data preparation will be skipped, and the function will return immediately.

    Returns
    -------
    None
    """
    if skip_prep:
        logger.info("Skipping data preparation as `skip_prep` is set to `True`")
        return

    # check that `splits` input is valid
    for split in splits:
        assert (
            split in SPLITS + TRAIN_SUBSET
        ), f"Split {split} not recognized. Valid splits are {SPLITS + TRAIN_SUBSET}."

    # check that we are not using multiple train subsets
    if len(set(splits).intersection(TRAIN_SUBSET)) > 1:
        raise ValueError(
            "You cannot use multiple train subsets. Please select only one train subset."
        )

    os.makedirs(save_folder, exist_ok=True)

    # Setting output files
    save_csv_files = {}
    for split in splits:
        if split in TRAIN_SUBSET:
            save_csv_files[split] = os.path.join(save_folder, "train.csv")
        else:
            save_csv_files[split] = os.path.join(
                save_folder, f"{split.lower()}.csv"
            )

    # check if the data is already prepared
    if skip(save_csv_files):
        logger.info("Skipping preparation, completed in previous run.")
        return
    else:
        logger.info("Starting data preparation...")

    check_gigaspeech_folders(data_folder, json_file)

    json_metadata = os.path.join(data_folder, json_file)
    logger.info(f"Starting reading {json_file}.")
    with open(json_metadata, "r") as f:
        info = json.load(f)
    logger.info(f"Reading {json_file} done.")

    logger.info("Creating train, dev, and test subsets.")
    for split, output_csv_file in save_csv_files.items():
        logger.info(f"Starting creating {output_csv_file} using {split} split.")
        create_csv(output_csv_file, info, data_folder, split)
    logger.info("Data preparation completed!")


def process_line(audio: json, data_folder: str, split: str) -> list:
    """
    Process the audio line and return the utterances for the given split.

    Parameters
    ----------
    audio : dict
        The audio line to be processed.
    data_folder : str
        The path to the GigaSpeech dataset.
    split : str
        The split to be used for filtering the data.

    Returns
    -------
    list
        The list of utterances for the given split.
    """
    if ("{" + split + "}") in audio["subsets"]:

        audio_path = os.path.join(data_folder, audio["path"])
        assert os.path.isfile(audio_path), f"File not found: {audio_path}"

        # 2. iterate over the utterances
        utterances = []
        for segment in audio["segments"]:
            text = preprocess_text(segment["text_tn"])
            if text:
                begin_time = float(segment["begin_time"])
                end_time = float(segment["end_time"])
                duration = end_time - begin_time
                utterance = GigaSpeechRow(
                    utt_id=segment["sid"],
                    audio_id=audio["aid"],
                    audio_path=str(audio_path),
                    speaker=audio["speaker"],
                    begin_time=begin_time,
                    end_time=end_time,
                    duration=duration,
                    text=text,
                )
                utterances.append(utterance)
        return utterances


def create_csv(csv_file: str, info: json, data_folder: str, split: str) -> None:
    """
    Create a CSV file based on the info in the GigaSpeech JSON file and filter the data based on the split.

    Parameters
    ----------
    csv_file : str
        The path to the CSV file to be created.
    info : dict
        The GigaSpeech JSON file content.
    data_folder : str
        The path to the GigaSpeech dataset.
    split : str
        The split to be used for filtering the data.

    Returns
    -------
    None
    """
    total_duration = 0.0
    nb_samples = 0

    line_processor = functools.partial(
        process_line, data_folder=data_folder, split=split,
    )

    csv_file_tmp = csv_file + ".tmp"
    with open(csv_file_tmp, mode="w", encoding="utf-8") as csv_f:
        csv_writer = csv.writer(
            csv_f, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL
        )
        header = [
            "utt_id",
            "audio_id",
            "audio_path",
            "speaker",
            "begin_time",
            "end_time",
            "duration",
            "text",
        ]
        csv_writer.writerow(header)
        for row in parallel_map(line_processor, info["audios"]):
            if row is None:
                continue

            for item in row:
                csv_writer.writerow(
                    [
                        item.utt_id,
                        item.audio_id,
                        item.audio_path,
                        item.speaker,
                        str(item.begin_time),
                        str(item.end_time),
                        str(item.duration),
                        item.text,
                    ]
                )

                total_duration += item.duration
                nb_samples += 1

    os.replace(csv_file_tmp, csv_file)

    logger.info(f"{csv_file} succesfully created!")
    logger.info(f"Number of samples in {split} split: {nb_samples}")
    logger.info(
        f"Total duration of {split} split: {round(total_duration / 3600, 2)} Hours"
    )


def preprocess_text(text: str) -> str:
    """
    Preprocesses the input text by removing garbage tags and replacing punctuation tags.

    Parameters
    ----------
    text : str
        The input text to be preprocessed.

    Returns
    -------
    str
        The preprocessed text with removed garbage tags and replaced punctuation tags.

    Raises
    ------
    AssertionError
        If '<' or '>' tags are found in the text after preprocessing.

    Notes
    -----
    The function iterates over predefined garbage utterance tags (GRABAGE_UTTERANCE_TAGS)
    and removes them from the input text. It then iterates over predefined punctuation tags
    (PUNCTUATION_TAGS) and replaces them with the corresponding punctuation.

    Examples
    --------
    >>> text = " DOUGLAS MCGRAY IS GOING TO BE OUR GUIDE YOU WALK THROUGH THE DOOR <COMMA> YOU SEE THE RED CARPETING <COMMA> YOU SEE SOMEONE IN A SUIT <PERIOD> THEY MAY BE GREETING YOU <PERIOD>"
    >>> preprocess_text(text)
    "douglas mcgray is going to be our guide you walk through the door, you see the red carpeting, you see someone in a suit. they may be greeting you."
    """
    # Remove garbage tags
    for tag in GRABAGE_UTTERANCE_TAGS:
        if tag in text:
            return ""

    # Remove punctuation tags
    for tag, punctuation in PUNCTUATION_TAGS.items():
        text = text.replace(" " + tag, punctuation)

    assert (
        "<" not in text and ">" not in text
    ), f"Found tags in the text: {text}"
    return text.lower()


def skip(save_csv_files: dict) -> bool:
    """ Check if the CSV files already exist.

    Parameters
    ----------
    save_csv_files : dict
        The dictionary containing the paths to the CSV files.

    Returns
    -------
    bool
        True if all the CSV files already exist, False otherwise.
    """
    return all(os.path.isfile(path) for path in save_csv_files.values())


def check_gigaspeech_folders(
    data_folder: str,
    json_file: str = "GigaSpeech.json",
    audio_folder: str = "audio",
) -> None:
    """Check if the data folder actually contains the GigaSpeech dataset.

    If it does not, an error is raised.

    Parameters
    ----------
    data_folder : str
        The path to the GigaSpeech dataset.
    json_file : str, optional
        The name of the JSON file containing the metadata of the GigaSpeech dataset.
    audio_folder : str, optional
        The name of the folder containing the audio files of the GigaSpeech dataset.

    Returns
    -------
    None

    Raises
    ------
    OSError
        If GigaSpeech is not found at the specified path.
    """
    # Checking if "GigaSpeech.json" exist
    json_gigaspeech = os.path.join(data_folder, json_file)

    if not os.path.exists(json_gigaspeech):
        err_msg = (
            "the opus file %s does not exist (it is expected in the "
            "Gigaspeech dataset)" % json_gigaspeech
        )
        raise OSError(err_msg)

    # Check if audio folders exist
    for folder_subset in ["audiobook", "podcast", "youtube"]:
        audio_subset = os.path.join(data_folder, audio_folder, folder_subset)
        if not os.path.exists(audio_subset):
            err_msg = (
                "the file %s does not exist (it is expected in the "
                "Gigaspeech dataset)" % audio_subset
            )
            raise OSError(err_msg)
