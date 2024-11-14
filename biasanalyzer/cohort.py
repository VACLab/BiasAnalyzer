from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from datetime import datetime
from biasanalyzer.models import CohortDefinition, Cohort
from biasanalyzer.database import OMOPCDMDatabase, BiasDatabase
from biasanalyzer.utils import hellinger_distance


class CohortData:
    def __init__(self, cohort_id: int, bias_db: BiasDatabase, omop_db: OMOPCDMDatabase):
        self.cohort_id = cohort_id
        self.bias_db = bias_db
        self.omop_db = omop_db
        self._cohort_data = None # cache the cohort data
        self._metadata = None

    @property
    def data(self):
        """
        query the database to get the cohort data using cohort_id. Return cached data if already fetched
        :return: cohort data
        """
        if self._cohort_data is None:
            self._cohort_data = self.bias_db.get_cohort(self.cohort_id)
        return self._cohort_data

    @property
    def metadata(self):
        if self._metadata is None:
            self._metadata = self.bias_db.get_cohort_definition(self.cohort_id)
        return self._metadata

    def get_stats(self, variable=''):
        """
        Get aggregation statistics for the cohort in BiasDatabase.
        variable is optional with a default empty string. Supported variables are: age, gender,
        race, and ethnicity.
        """
        return self.bias_db.get_cohort_basic_stats(self.cohort_id, variable=variable)

    def get_distributions(self, variable):
        """
        Get distribution statistics for a variable (e.g., age) in a specific cohort in BiasDatabase.
        """
        return self.bias_db.get_cohort_distributions(self.cohort_id, variable)

    def get_concept_stats(self):
        """
        Get cohort concept statistics such as concept prevalence
        """
        return self.bias_db.get_cohort_concept_stats(self.cohort_id)

    def __del__(self):
        self._cohort_data = None
        self._metadata = None


class CohortAction:
    def __init__(self, omop_db: OMOPCDMDatabase, bias_db: BiasDatabase):
        self.omop_db = omop_db
        self.bias_db = bias_db

    def create_cohort(self, cohort_name: str, description: str, query: str, created_by: str):
        """
        Create a new cohort by executing a query on OMOP CDM database
        and storing the result in BiasDatabase.
        """
        omop_session = self.omop_db.get_session()
        try:
            query = text(query)
            # Execute read-only query from OMOP CDM database
            result = omop_session.execute(query).mappings().fetchall()
            # Create CohortDefinition
            cohort_def = CohortDefinition(
                name=cohort_name,
                description=description,
                created_date=datetime.now().date(),
                creation_info=str(query),
                created_by=created_by
            )
            cohort_def_id = self.bias_db.create_cohort_definition(cohort_def)

            # Store cohort_definition and cohort data into BiasDatabase
            for row in result:
                cohort = Cohort(
                    subject_id=int(row['person_id']),  # Assuming person_id column in the result
                    cohort_definition_id=cohort_def_id,
                    cohort_start_date=row['cohort_start_date'],
                    cohort_end_date=row['cohort_end_date']
                )
                self.bias_db.create_cohort(cohort)
            print(f"Cohort {cohort_name} successfully created.")
            omop_session.close()
            return CohortData(cohort_id=cohort_def_id, bias_db=self.bias_db, omop_db=self.omop_db)
        except SQLAlchemyError as e:
            print(f"Error executing query: {e}")
            omop_session.close()

    def compare_cohorts(self, cohort_id_1: int, cohort_id_2: int):
        """
        Compare the distributions of two cohorts in BiasDatabase.
        """
        results = []
        for variable in self.bias_db.cohort_distribution_variables:
            cohort_1_stats = self.bias_db.get_cohort_distributions(cohort_id_1, variable=variable)
            cohort_2_stats = self.bias_db.get_cohort_distributions(cohort_id_2, variable=variable)
            cohort_1_probs = [entry['probability'] for entry in cohort_1_stats]
            cohort_2_probs = [entry['probability'] for entry in cohort_2_stats]
            dist = hellinger_distance(cohort_1_probs, cohort_2_probs)
            results.append({
                f'{variable}_hellinger_distance': dist
            })

        return results